"""Container extras own every optional import reachable from their entrypoints."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import distributions, packages_distributions
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"


@dataclass(frozen=True)
class ContainerSpec:
    compose_service: str
    dockerfile: Path
    extras: frozenset[str]
    entrypoint: str
    startup_modules: tuple[str, ...]
    command: tuple[str, ...] | None


CONTAINERS = {
    "web": ContainerSpec(
        "songmaker-web",
        Path("Dockerfile"),
        frozenset({"server", "mcp", "claude"}),
        "songmaker_cli.main",
        ("songmaker_cli.main", "songmaker_cli.server"),
        None,
    ),
    "scoring-worker": ContainerSpec(
        "songmaker-scoring-worker",
        Path("docker/scoring-worker.Dockerfile"),
        frozenset({"server", "scoring", "whisper", "claude"}),
        "songmaker_cli.scoring_worker",
        ("songmaker_cli.scoring_worker",),
        ("songmaker_cli.scoring_worker.ScoringWorkerSettings",),
    ),
    "music-worker": ContainerSpec(
        "songmaker-music-worker",
        Path("docker/music-worker.Dockerfile"),
        frozenset({"server"}),
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
    "bcrypt": frozenset({"bcrypt"}),
    "fakeredis": frozenset({"fakeredis"}),
    "fastapi": frozenset({"fastapi"}),
    "faster-whisper": frozenset({"faster_whisper"}),
    "huggingface-hub": frozenset({"huggingface_hub"}),
    "librosa": frozenset({"librosa"}),
    "mcp": frozenset({"mcp"}),
    "mutagen": frozenset({"mutagen"}),
    "numba": frozenset({"numba"}),
    "nvidia-ml-py3": frozenset({"nvidia_smi", "pynvml"}),
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
    "soundfile": frozenset({"_soundfile", "_soundfile_data", "soundfile"}),
    "sqlalchemy": frozenset({"sqlalchemy"}),
    "structlog": frozenset({"structlog"}),
    "torch": frozenset({"functorch", "torch", "torchgen"}),
    "torchaudio": frozenset({"torchaudio", "torio"}),
    "uvicorn": frozenset({"uvicorn"}),
}


def _normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _optional_extras_by_distribution() -> dict[str, frozenset[str]]:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    result: dict[str, set[str]] = {}
    for extra, requirements in pyproject["project"]["optional-dependencies"].items():
        for requirement in requirements:
            match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
            assert match, f"could not parse optional dependency {requirement!r}"
            distribution = _normalized_distribution(match.group())
            result.setdefault(distribution, set()).add(extra)
    return {distribution: frozenset(extras) for distribution, extras in result.items()}


def _root_owning_extras() -> dict[str, frozenset[str]]:
    extras_by_distribution = _optional_extras_by_distribution()
    result: dict[str, set[str]] = {}
    for distribution, roots in OPTIONAL_DISTRIBUTION_ROOTS.items():
        for root in roots:
            result.setdefault(root, set()).update(extras_by_distribution[distribution])
    return {root: frozenset(extras) for root, extras in result.items()}


def _sync_extras(dockerfile: Path) -> list[frozenset[str]]:
    logical_lines: list[str] = []
    current_line = ""
    for line in dockerfile.read_text().splitlines():
        current_line += line.rstrip().removesuffix("\\") + " "
        if line.rstrip().endswith("\\"):
            continue
        logical_lines.append(current_line)
        current_line = ""
    return [
        frozenset(re.findall(r"--extra\s+([A-Za-z0-9-]+)", line))
        for line in logical_lines
        if "uv sync" in line
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


def _raw_compose() -> dict[str, object]:
    compose = yaml.safe_load((REPOSITORY_ROOT / "docker-compose.yml").read_text())
    assert isinstance(compose, dict)
    return compose


def _raw_compose_services() -> dict[str, object]:
    compose = _raw_compose()
    services = compose["services"]
    assert isinstance(services, dict)
    return services


def _declared_named_volumes() -> frozenset[str]:
    volumes = _raw_compose()["volumes"]
    assert isinstance(volumes, dict)
    return frozenset(volumes)


def _service_dockerfile(service_block: str) -> Path:
    match = re.search(r"^      dockerfile: (.+)$", service_block, re.MULTILINE)
    assert match, "service has no build dockerfile"
    return Path(match.group(1))


def _service_command(service_block: str) -> tuple[str, ...] | None:
    match = re.search(r"^    command: \[(.+)\]$", service_block, re.MULTILINE)
    if match is None:
        return None
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


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
        assert _service_dockerfile(service_block) == spec.dockerfile
        assert _service_command(service_block) == spec.command

    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    web_dockerfile = (REPOSITORY_ROOT / CONTAINERS["web"].dockerfile).read_text()
    web_entrypoint = (REPOSITORY_ROOT / "docker-entrypoint.sh").read_text()

    assert pyproject["project"]["scripts"]["songmaker"] == "songmaker_cli.main:main"
    assert 'ENTRYPOINT ["/app/docker-entrypoint.sh"]' in web_dockerfile
    assert "exec uv run songmaker server" in web_entrypoint
    assert CONTAINERS["web"].startup_modules == (
        "songmaker_cli.main", "songmaker_cli.server",
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

    assert extras_by_distribution["anthropic"] == frozenset({"claude"})
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


def test_both_provider_facing_images_ship_the_claude_sdk() -> None:
    """The documented ANTHROPIC_API_KEY path is installed in both images."""
    owns_the_sdk = _optional_extras_by_distribution()["anthropic"]

    for container in ("web", "scoring-worker"):
        assert CONTAINERS[container].extras & owns_the_sdk, container
    assert not CONTAINERS["music-worker"].extras & owns_the_sdk


def test_agent_cli_mounts_reject_short_syntax_and_host_profiles() -> None:
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
    }
    expected_sources_by_service = {
        "songmaker-web": expected_web_sources_by_target,
        "songmaker-scoring-worker": {
            target: source
            for target, source in expected_web_sources_by_target.items()
            if target in {
                "/usr/local/bin/claude",
                "/home/songmaker/.claude/.credentials.json",
            }
        },
    }
    services = _raw_compose_services()
    declared_named_volumes = _declared_named_volumes()

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
            assert source == expected_sources_by_target[target]
            assert mount.get("read_only") is True
            bind_options = mount.get("bind")
            assert isinstance(bind_options, dict)
            assert bind_options.get("create_host_path") is False
