"""Container extras own every optional import reachable from their entrypoints."""

from __future__ import annotations

import functools
import ipaddress
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import distributions, packages_distributions
from pathlib import Path

import pytest
import yaml
from conftest import REPOSITORY_ROOT, run_compose_config

SOURCE_ROOT = REPOSITORY_ROOT / "src"
DOCKER_ROOT = REPOSITORY_ROOT / "docker"
UV_INSTALLED_ENVIRONMENT_FLAGS = frozenset({"--no-sync", "--frozen", "--no-build"})
IMAGE_VIRTUALENV_BIN = "/app/.venv/bin/"
WEB_ENTRYPOINT_SCRIPT = "/app/docker-entrypoint.sh"
E2E_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "e2e.yml"
VOICES_E2E_OVERLAY = ("-f", "docker/docker-compose.e2e-voices.yml")
DOCKER_DEFAULT_RESTART_POLICY = "no"


@dataclass(frozen=True)
class ContainerSpec:
    compose_service: str
    dockerfile: Path
    extras: frozenset[str]
    entrypoint: str
    startup_modules: tuple[str, ...]
    command: tuple[str, ...] | None


@dataclass(frozen=True)
class ContainerStart:
    declared_at: str
    command: tuple[str, ...]


CONTAINERS = {
    "web": ContainerSpec(
        "songmaker-web",
        Path("Dockerfile"),
        frozenset({"server", "mcp", "agent-service", "api", "image"}),
        "songmaker_cli.main",
        ("songmaker_cli.main", "songmaker_cli.server"),
        None,
    ),
    "scoring-worker": ContainerSpec(
        "songmaker-scoring-worker",
        Path("docker/scoring-worker.Dockerfile"),
        frozenset({"server", "scoring", "whisper"}),
        "songmaker_cli.scoring_worker",
        ("songmaker_cli.scoring_worker",),
        ("songmaker_cli.scoring_worker.ScoringWorkerSettings",),
    ),
    "music-worker": ContainerSpec(
        "songmaker-music-worker",
        Path("docker/music-worker.Dockerfile"),
        frozenset({"server", "image"}),
        "songmaker_cli.music_worker",
        ("songmaker_cli.music_worker",),
        ("songmaker_cli.music_worker.MusicWorkerSettings",),
    ),
}


OPTIONAL_DISTRIBUTION_ROOTS = {
    "alembic": frozenset({"alembic"}),
    "anthropic": frozenset({"anthropic"}),
    "audiobox-aesthetics": frozenset({"audiobox_aesthetics"}),
    "arq": frozenset({"arq"}),
    "fakeredis": frozenset({"fakeredis"}),
    "fastapi": frozenset({"fastapi"}),
    "faster-whisper": frozenset({"faster_whisper"}),
    "huggingface-hub": frozenset({"huggingface_hub"}),
    "import-linter": frozenset({"importlinter"}),
    "librosa": frozenset({"librosa"}),
    "mcp": frozenset({"mcp"}),
    "mutagen": frozenset({"mutagen"}),
    "numba": frozenset({"numba"}),
    "nvidia-ml-py3": frozenset({"nvidia_smi", "pynvml"}),
    "overnightworks-agent-providers": frozenset({"agent_providers"}),
    "overnightworks-agent-runtime-client": frozenset({"agent_runtime_client"}),
    "overnightworks-webauth": frozenset({"webauth"}),
    "pillow": frozenset({"PIL"}),
    "psycopg2-binary": frozenset({"psycopg2"}),
    "pytest": frozenset({"_pytest", "py", "pytest"}),
    "pytest-cov": frozenset({"pytest_cov"}),
    "pytest-xdist": frozenset({"xdist"}),
    "python-dotenv": frozenset({"dotenv"}),
    "python-multipart": frozenset({"multipart", "python_multipart"}),
    "pyyaml": frozenset({"_yaml", "yaml"}),
    "redis": frozenset({"redis"}),
    "ruff": frozenset({"ruff"}),
    "sentence-transformers": frozenset({"sentence_transformers"}),
    "soundfile": frozenset({"_soundfile", "_soundfile_data", "soundfile"}),
    "sqlalchemy": frozenset({"sqlalchemy"}),
    "structlog": frozenset({"structlog"}),
    "torch": frozenset({"functorch", "torch", "torchgen"}),
    "torchaudio": frozenset({"torchaudio"}),
    # torchcodec's top_level.txt lists a placeholder root next to the real one.
    "torchcodec": frozenset({"FAKE_NAME", "torchcodec"}),
    "uvicorn": frozenset({"uvicorn"}),
}


def _normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_distribution(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    assert match, f"could not parse dependency {requirement!r}"
    return _normalized_distribution(match.group())


def _core_distributions() -> frozenset[str]:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    return frozenset(
        _requirement_distribution(requirement)
        for requirement in pyproject["project"]["dependencies"]
    )


def _optional_extras_by_distribution() -> dict[str, frozenset[str]]:
    """Map every genuinely optional distribution to the extras that install it.

    A distribution the project also requires unconditionally is installed in
    every container whatever its extras, so naming it in an extra says what
    that extra needs without making it omittable — ``httpx`` is both
    songmaker's own HTTP client and part of the provider layer's ``api``
    capability (issue #871).
    """
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    core = _core_distributions()
    result: dict[str, set[str]] = {}
    for extra, requirements in pyproject["project"]["optional-dependencies"].items():
        for requirement in requirements:
            distribution = _requirement_distribution(requirement)
            if distribution in core:
                continue
            result.setdefault(distribution, set()).add(extra)
    return {distribution: frozenset(extras) for distribution, extras in result.items()}


def _root_owning_extras() -> dict[str, frozenset[str]]:
    extras_by_distribution = _optional_extras_by_distribution()
    result: dict[str, set[str]] = {}
    for distribution, roots in OPTIONAL_DISTRIBUTION_ROOTS.items():
        for root in roots:
            result.setdefault(root, set()).update(extras_by_distribution[distribution])
    return {root: frozenset(extras) for root, extras in result.items()}


def _dockerfile_instructions(dockerfile: Path) -> list[str]:
    instructions: list[str] = []
    current_instruction = ""
    for line in dockerfile.read_text().splitlines():
        current_instruction += line.rstrip().removesuffix("\\") + " "
        if line.rstrip().endswith("\\"):
            continue
        instructions.append(current_instruction.strip())
        current_instruction = ""
    return instructions


def _sync_extras(dockerfile: Path) -> list[frozenset[str]]:
    return [
        frozenset(re.findall(r"--extra\s+([A-Za-z0-9-]+)", instruction))
        for instruction in _dockerfile_instructions(dockerfile)
        if "uv sync" in instruction
    ]


def _container_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({
        "PYTHONPATH": str(SOURCE_ROOT),
        "SONGMAKER_SKIP_ENV_FILE": "1",
        "DATABASE_URL": "postgresql://songmaker:songmaker@localhost/songmaker",
        "REDIS_URL": "redis://localhost:6379/0",
        "SESSION_SECRET": "packaging-boundary-test",
        "SONGMAKER_INTERNAL_TOKEN": "packaging-boundary-test",
    })
    return environment


def _compose_service_block(service: str) -> str:
    lines = (REPOSITORY_ROOT / "docker-compose.yml").read_text().splitlines()
    service_line = f"  {service}:"
    start = lines.index(service_line)
    block: list[str] = []
    for line in lines[start + 1:]:
        if re.fullmatch(r"  [A-Za-z0-9_-]+:", line):
            break
        block.append(line)
    return "\n".join(block)


class _ComposeLoader(yaml.SafeLoader):
    """Reads compose's merge tags (``!reset``, ``!override``) as their plain values."""


def _construct_compose_merge_tag(loader: yaml.SafeLoader, node: yaml.Node) -> object:
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_scalar(node)


for _compose_merge_tag in ("!reset", "!override"):
    _ComposeLoader.add_constructor(_compose_merge_tag, _construct_compose_merge_tag)


def _compose_file(path: Path) -> dict[str, object]:
    compose = yaml.load(path.read_text(), Loader=_ComposeLoader)
    assert isinstance(compose, dict)
    return compose


def _raw_compose() -> dict[str, object]:
    return _compose_file(REPOSITORY_ROOT / "docker-compose.yml")


def _raw_compose_services() -> dict[str, object]:
    compose = _raw_compose()
    services = compose["services"]
    assert isinstance(services, dict)
    return services


def _declared_named_volumes() -> frozenset[str]:
    volumes = _raw_compose()["volumes"]
    assert isinstance(volumes, dict)
    return frozenset(volumes)


@functools.cache
def _e2e_workflow_environment() -> dict[str, str]:
    workflow = yaml.safe_load(E2E_WORKFLOW.read_text())
    return {name: str(value) for name, value in workflow["env"].items()}


def _e2e_workflow_compose_files() -> tuple[str, ...]:
    return tuple(shlex.split(_e2e_workflow_environment()["COMPOSE_FILES"]))


def _test_stacks() -> dict[str, tuple[str, ...]]:
    workflow_files = _e2e_workflow_compose_files()
    return {
        "e2e-workflow": workflow_files,
        "voices-e2e": (*workflow_files, *VOICES_E2E_OVERLAY),
    }


TEST_STACKS = _test_stacks()


@functools.cache
def _rendered_test_stack_services(
    compose_files: tuple[str, ...], operator_environment: tuple[tuple[str, str], ...] = (),
) -> dict[str, dict]:
    """The test stack as Compose itself merges it, every profile active, under e2e.yml's env.

    ``operator_environment`` adds what an operator's ``.env`` would set on top of it.
    """
    rendered = run_compose_config(
        (*compose_files, "--profile", "*"),
        ("--format", "json"),
        env_file=Path(os.devnull),
        environment={**_e2e_workflow_environment(), **dict(operator_environment)},
    )
    assert rendered.returncode == 0, rendered.stderr
    return json.loads(rendered.stdout)["services"]


def _binds_loopback_only(host_ip: str) -> bool:
    return bool(host_ip) and ipaddress.ip_address(host_ip).is_loopback


def _service_dockerfile(service: str) -> Path:
    build = _raw_compose_services()[service]["build"]
    return Path(build["dockerfile"])


def _service_command(service_block: str) -> tuple[str, ...] | None:
    match = re.search(r"^    command: \[(.+)\]$", service_block, re.MULTILINE)
    if match is None:
        return None
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


def _command_words(declaration: str | list[str]) -> tuple[str, ...]:
    if isinstance(declaration, list):
        return tuple(declaration)
    if declaration.startswith("["):
        return tuple(json.loads(declaration))
    return tuple(shlex.split(declaration))


def _relative(path: Path) -> str:
    return str(path.relative_to(REPOSITORY_ROOT))


def _compose_entrypoint_starts() -> list[ContainerStart]:
    compose_files = [
        REPOSITORY_ROOT / "docker-compose.yml",
        *sorted(DOCKER_ROOT.glob("docker-compose*.yml")),
    ]
    services_by_file = {path: _compose_file(path)["services"] for path in compose_files}
    repo_built_services = {
        name
        for services in services_by_file.values()
        for name, service in services.items()
        if "build" in service
    }
    return [
        ContainerStart(f"{_relative(path)}::{name}", _command_words(service["entrypoint"]))
        for path, services in services_by_file.items()
        for name, service in services.items()
        if name in repo_built_services and "entrypoint" in service
    ]


def _dockerfile_entrypoint_starts() -> list[ContainerStart]:
    dockerfiles = [REPOSITORY_ROOT / "Dockerfile", *sorted(DOCKER_ROOT.rglob("*Dockerfile"))]
    return [
        ContainerStart(
            f"{_relative(dockerfile)}::ENTRYPOINT",
            _command_words(instruction.removeprefix("ENTRYPOINT").strip()),
        )
        for dockerfile in dockerfiles
        for instruction in _dockerfile_instructions(dockerfile)
        if instruction.startswith("ENTRYPOINT ")
    ]


def _entrypoint_script_starts() -> list[ContainerStart]:
    return [
        ContainerStart(f"{_relative(script)}::exec", tuple(shlex.split(line)[1:]))
        for script in sorted(DOCKER_ROOT.glob("*.sh"))
        for line in script.read_text().splitlines()
        if line.strip().startswith("exec ")
    ]


def _repo_built_container_starts() -> list[ContainerStart]:
    starts = [
        *_compose_entrypoint_starts(),
        *_dockerfile_entrypoint_starts(),
        *_entrypoint_script_starts(),
    ]
    assert starts, "found no container start to check"
    return starts


def _import_startup_modules(
    spec: ContainerSpec, blocked_roots: frozenset[str],
) -> subprocess.CompletedProcess[str]:
    return _run_with_blocked_optional_imports(
        spec,
        blocked_roots,
        "for startup_module in startup_modules:\n    importlib.import_module(startup_module)",
    )


def _run_with_blocked_optional_imports(
    spec: ContainerSpec,
    blocked_roots: frozenset[str],
    statement: str,
    extra_environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = """
import importlib
import importlib.abc
import sys

entrypoint = {entrypoint!r}
startup_modules = {startup_modules!r}
blocked_roots = frozenset({blocked_roots!r})

class BlockedOptionalImport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.partition('.')[0]
        if root in blocked_roots:
            raise ModuleNotFoundError(f"container dependency deliberately omitted: {{root}}")
        return None

sys.meta_path.insert(0, BlockedOptionalImport())
{statement}
""".format(
        blocked_roots=tuple(sorted(blocked_roots)),
        entrypoint=spec.entrypoint,
        startup_modules=spec.startup_modules,
        statement=statement,
    )
    environment = _container_environment()
    if extra_environment:
        environment.update(extra_environment)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_health_api_models_import_without_server_runtime() -> None:
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; import songmaker_cli.api_models; "
            "assert not {'arq', 'sqlalchemy'} & sys.modules.keys()",
        ],
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_container_extras_match_every_uv_sync_line() -> None:
    for name, spec in CONTAINERS.items():
        sync_extras = _sync_extras(REPOSITORY_ROOT / spec.dockerfile)
        assert sync_extras, f"{name} has no uv sync line"
        assert all(extras == spec.extras for extras in sync_extras), (
            f"{name} expected {sorted(spec.extras)}, got "
            f"{[sorted(extras) for extras in sync_extras]}"
        )


def test_container_entrypoints_match_runtime_configuration() -> None:
    for spec in CONTAINERS.values():
        service_block = _compose_service_block(spec.compose_service)
        assert _service_dockerfile(spec.compose_service) == spec.dockerfile
        assert _service_command(service_block) == spec.command

    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    web_dockerfile = (REPOSITORY_ROOT / CONTAINERS["web"].dockerfile).read_text()
    web_entrypoint = (REPOSITORY_ROOT / "docker" / "docker-entrypoint.sh").read_text()

    assert pyproject["project"]["scripts"]["songmaker"] == "songmaker_cli.main:main"
    assert 'ENTRYPOINT ["/app/docker-entrypoint.sh"]' in web_dockerfile
    assert "exec uv run --no-sync --frozen --no-build songmaker server" in web_entrypoint
    assert CONTAINERS["web"].startup_modules == (
        "songmaker_cli.main", "songmaker_cli.server",
    )


@pytest.mark.parametrize(
    "start", _repo_built_container_starts(), ids=lambda start: start.declared_at,
)
def test_every_repo_built_container_start_uses_the_installed_environment(
    start: ContainerStart,
) -> None:
    """A start that lets uv sync or build would need GitHub to boot (#1349)."""
    launcher, *arguments = start.command
    if launcher == "uv":
        assert arguments[:1] == ["run"], f"{start.declared_at} runs uv {arguments[:1]}"
        uv_options = frozenset(
            itertools.takewhile(lambda word: word.startswith("-"), arguments[1:]),
        )
        missing_flags = UV_INSTALLED_ENVIRONMENT_FLAGS - uv_options
        assert not missing_flags, f"{start.declared_at} lacks {sorted(missing_flags)}"
    else:
        assert launcher.startswith(IMAGE_VIRTUALENV_BIN) or launcher == WEB_ENTRYPOINT_SCRIPT, (
            f"{start.declared_at} starts through {launcher!r}"
        )


def test_optional_dependency_root_mapping_is_complete_and_metadata_verified() -> None:
    extras_by_distribution = _optional_extras_by_distribution()
    assert set(OPTIONAL_DISTRIBUTION_ROOTS) == set(extras_by_distribution)

    installed_distributions = {
        _normalized_distribution(distribution.metadata["Name"])
        for distribution in distributions()
    }
    installed_roots = packages_distributions()
    for distribution, roots in OPTIONAL_DISTRIBUTION_ROOTS.items():
        if distribution not in installed_distributions:
            continue
        metadata_roots = frozenset(
            root for root, owners in installed_roots.items()
            if distribution in {_normalized_distribution(owner) for owner in owners}
        )
        assert roots == metadata_roots

    assert extras_by_distribution["anthropic"] == frozenset({"api"})
    assert extras_by_distribution["pillow"] == frozenset({"image"})
    assert "httpx" in _core_distributions()
    assert "httpx" not in extras_by_distribution
    assert "hiredis" not in _root_owning_extras()
    assert "lupa" not in _root_owning_extras()


def test_container_entrypoints_do_not_import_omitted_optional_dependencies() -> None:
    root_owners = _root_owning_extras()
    for name, spec in CONTAINERS.items():
        blocked_roots = frozenset(
            root for root, owners in root_owners.items() if not owners & spec.extras
        )
        completed = _import_startup_modules(spec, blocked_roots)
        assert completed.returncode == 0, (
            f"{name} ({spec.entrypoint}) imported an omitted optional dependency.\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def test_the_mcp_server_spec_imports_without_the_mcp_extra() -> None:
    """The scoring-worker container installs no ``mcp`` extra, so songmaker's
    MCP declaration must stay outside ``mcp_server/`` — whose ``__init__``
    imports that extra eagerly (ruling ac on #825)."""
    spec = CONTAINERS["scoring-worker"]
    blocked_roots = frozenset(
        root for root, owners in _root_owning_extras().items()
        if not owners & spec.extras
    )
    assert "mcp" in blocked_roots

    completed = _run_with_blocked_optional_imports(
        spec,
        blocked_roots,
        "importlib.import_module('songmaker_cli.cowriter.mcp_spec')",
    )

    assert completed.returncode == 0, (
        f"songmaker_cli.cowriter.mcp_spec reached an omitted optional "
        f"dependency.\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_the_scoring_worker_imports_the_image_route_without_pillow() -> None:
    """The scoring worker reaches the cover job's error names through
    ``jobs/_runtime.py`` but never produces an image, so it installs no
    ``image`` extra. Pillow must therefore stay behind the
    one call that encodes a picture (issue #871)."""
    spec = CONTAINERS["scoring-worker"]
    blocked_roots = frozenset(
        root for root, owners in _root_owning_extras().items()
        if not owners & spec.extras
    )
    assert "PIL" in blocked_roots

    completed = _run_with_blocked_optional_imports(
        spec,
        blocked_roots,
        "importlib.import_module('agent_providers.codex.image')",
    )

    assert completed.returncode == 0, (
        f"agent_providers.codex.image reached an omitted optional "
        f"dependency.\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_only_the_web_image_ships_the_claude_sdk() -> None:
    """The documented ANTHROPIC_API_KEY path is installed where it is used."""
    owns_the_sdk = _optional_extras_by_distribution()["anthropic"]

    assert CONTAINERS["web"].extras & owns_the_sdk
    for container in ("music-worker", "scoring-worker"):
        assert not CONTAINERS[container].extras & owns_the_sdk, container


def test_check_agent_cli_mounts_rejects_short_syntax_and_host_profiles() -> None:
    expected_web_sources_by_target = {
        "/usr/local/bin/claude": "${SONGMAKER_CLAUDE_CLI:-~/.local/bin/claude}",
        "/home/songmaker/.claude/.credentials.json": (
            "${SONGMAKER_CLI_CREDENTIALS_DIR:-~/.songmaker/agent-cli-credentials}"
            "/claude.json"
        ),
        "/usr/local/bin/grok": "${SONGMAKER_GROK_CLI:-~/.grok/bin/grok}",
        "/home/songmaker/.grok/auth.json": (
            "${SONGMAKER_CLI_CREDENTIALS_DIR:-~/.songmaker/agent-cli-credentials}"
            "/grok.json"
        ),
        "/usr/local/bin/codex": (
            "${SONGMAKER_CODEX_CLI:-~/.local/node/lib/node_modules/@openai/codex/"
            "node_modules/@openai/codex-linux-x64/vendor/"
            "x86_64-unknown-linux-musl/bin/codex}"
        ),
        "/home/songmaker/.codex/auth.json": (
            "${SONGMAKER_CLI_CREDENTIALS_DIR:-~/.songmaker/agent-cli-credentials}"
            "/codex.json"
        ),
        "/usr/local/bin/codex-code-mode-host": (
            "${SONGMAKER_CODEX_CODE_MODE_HOST:-~/.local/node/lib/node_modules/"
            "@openai/codex/node_modules/@openai/codex-linux-x64/vendor/"
            "x86_64-unknown-linux-musl/bin/codex-code-mode-host}"
        ),
        "/usr/local/codex-resources": (
            "${SONGMAKER_CODEX_RESOURCES:-~/.local/node/lib/node_modules/"
            "@openai/codex/node_modules/@openai/codex-linux-x64/vendor/"
            "x86_64-unknown-linux-musl/codex-resources}"
        ),
    }
    expected_sources_by_service = {
        "songmaker-web": expected_web_sources_by_target,
        "songmaker-music-worker": {
            target: source
            for target, source in expected_web_sources_by_target.items()
            if target in {
                "/usr/local/bin/codex",
                "/home/songmaker/.codex/auth.json",
            }
        },
    }
    services = _raw_compose_services()
    declared_named_volumes = _declared_named_volumes()
    music_worker_dockerfile = (
        REPOSITORY_ROOT / CONTAINERS["music-worker"].dockerfile
    ).read_text()
    assert "mkdir -p /home/songmaker/.codex" in music_worker_dockerfile
    assert "bubblewrap" in (REPOSITORY_ROOT / "Dockerfile").read_text()

    for service_name, expected_sources_by_target in expected_sources_by_service.items():
        service = services[service_name]
        assert isinstance(service, dict)
        assert "extends" not in service, (
            f"{service_name} must not inherit mounts through Compose extends"
        )
        assert "volumes_from" not in service, (
            f"{service_name} must not inherit mounts through Compose volumes_from"
        )
        volumes = service["volumes"]
        assert isinstance(volumes, list)
        bind_mounts: list[dict[str, object]] = []
        for volume in volumes:
            if isinstance(volume, str):
                source = volume.split(":", maxsplit=1)[0]
                assert source in declared_named_volumes, (
                    f"{service_name} must use Compose long syntax for every bind "
                    f"mount so its read-only and host-path protections are explicit: "
                    f"{volume!r} is not a declared named volume"
                )
                continue

            assert isinstance(volume, dict), (
                f"{service_name} has an unsupported volume declaration: {volume!r}"
            )
            if volume.get("type") == "bind":
                bind_mounts.append(volume)
                continue

            assert volume.get("type") == "volume", (
                f"{service_name} volume mappings must declare their type: {volume!r}"
            )
            source = volume.get("source")
            assert source in declared_named_volumes, (
                f"{service_name} volume mapping has an undeclared source: {source!r}"
            )

        assert bind_mounts, service_name
        assert {mount.get("target") for mount in bind_mounts} == set(
            expected_sources_by_target,
        )

        for mount in bind_mounts:
            target = mount.get("target")
            assert isinstance(target, str)
            source = mount.get("source")
            assert isinstance(source, str)
            assert "~/.claude" not in source
            assert "~/.claude.json" not in source
            assert "~/.codex" not in source
            assert source == expected_sources_by_target[target]
            assert mount.get("read_only") is True
            bind_options = mount.get("bind")
            assert isinstance(bind_options, dict)
            assert bind_options.get("create_host_path") is False


WORKER_SERVICES = (
    "songmaker-music-worker",
    "songmaker-acestep-worker-0",
    "songmaker-scoring-worker",
)
WEB_ONLY_SECURITY_OPTIONS = ("seccomp", "apparmor", "systempaths")


@pytest.mark.parametrize("service_name", WORKER_SERVICES)
def test_a_worker_drops_every_capability_and_blocks_privilege_gain(
    service_name: str,
) -> None:
    service = _raw_compose_services()[service_name]
    assert isinstance(service, dict)
    security_options = service["security_opt"]

    assert service["cap_drop"] == ["ALL"]
    assert "cap_add" not in service
    assert not service.get("privileged")
    assert "no-new-privileges:true" in security_options
    assert not [
        option
        for option in security_options
        if option.startswith(WEB_ONLY_SECURITY_OPTIONS)
    ]


@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
def test_a_test_stack_publishes_its_ports_on_loopback_only(
    compose_files: tuple[str, ...],
) -> None:
    """Docker-published ports bypass ufw, so any other host IP reaches the LAN (#1355)."""
    published_ports = [
        (service_name, port)
        for service_name, service in _rendered_test_stack_services(compose_files).items()
        for port in service.get("ports", [])
    ]
    assert published_ports, "the test stack publishes no port"
    reachable_from_outside = [
        f"{service_name} publishes {port.get('host_ip') or '<every interface>'}"
        f":{port['published']}"
        for service_name, port in published_ports
        if not _binds_loopback_only(port.get("host_ip", ""))
    ]
    assert not reachable_from_outside


@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
def test_no_test_stack_service_comes_back_after_a_reboot(
    compose_files: tuple[str, ...],
) -> None:
    """A test stack nobody tore down must not restart with the machine (#1355)."""
    restart_policies = {
        service_name: service.get("restart", DOCKER_DEFAULT_RESTART_POLICY)
        for service_name, service in _rendered_test_stack_services(compose_files).items()
    }
    assert restart_policies == dict.fromkeys(restart_policies, "no")


@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
def test_only_the_web_service_holds_the_keycloak_client_secret(
    compose_files: tuple[str, ...],
) -> None:
    holders = {
        service_name
        for service_name, service in _rendered_test_stack_services(compose_files).items()
        if "keycloak_client_secret" in {s["source"] for s in service.get("secrets", [])}
    }
    assert holders == {"songmaker-web"}


@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
@pytest.mark.parametrize("operator_hosts", [None, "songmaker.hallucinai.de"])
def test_the_web_host_check_admits_the_names_the_stack_calls_it_by(
    compose_files: tuple[str, ...], operator_hosts: str | None,
) -> None:
    operator_environment = () if operator_hosts is None else (("ALLOWED_HOSTS", operator_hosts),)
    web = _rendered_test_stack_services(compose_files, operator_environment)["songmaker-web"]
    admitted = set(web["environment"]["ALLOWED_HOSTS"].split(","))
    assert {"localhost", "127.0.0.1", "songmaker-web"} <= admitted
    assert operator_hosts is None or operator_hosts in admitted
