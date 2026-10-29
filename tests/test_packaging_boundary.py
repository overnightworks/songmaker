"""Container extras own every optional import reachable from their entrypoints."""

from __future__ import annotations

import functools
import ipaddress
import itertools
import json
import os
import posixpath
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest
import yaml
from support.compose_config import run_compose_config
from support.repository_root import REPOSITORY_ROOT

SOURCE_ROOT = REPOSITORY_ROOT / "src"
DOCKER_ROOT = REPOSITORY_ROOT / "docker"
UV_INSTALLED_ENVIRONMENT_FLAGS = frozenset({"--no-sync", "--frozen", "--no-build"})
IMAGE_VIRTUALENV_BIN = "/app/.venv/bin/"
WEB_ENTRYPOINT_SCRIPT = "/app/docker-entrypoint.sh"
E2E_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "e2e.yml"
VOICES_E2E_OVERLAY = ("-f", "docker/docker-compose.e2e-voices.yml")
DOCKER_DEFAULT_RESTART_POLICY = "no"
WEB_SERVER_MODULE = "songmaker_cli.server"
SCORING_WORKER_SERVICE = "songmaker-scoring-worker"


@dataclass(frozen=True)
class ContainerSpec:
    extras: frozenset[str]
    startup_modules: tuple[str, ...]


@dataclass(frozen=True)
class ContainerStart:
    declared_at: str
    command: tuple[str, ...]


def _optional_distribution_roots() -> dict[str, frozenset[str]]:
    """Import roots of each installed optional distribution, from its metadata."""
    installed_roots = packages_distributions()
    result: dict[str, frozenset[str]] = {}
    for distribution in _optional_extras_by_distribution():
        roots = frozenset(
            root for root, owners in installed_roots.items()
            if distribution in {_normalized_distribution(owner) for owner in owners}
        )
        if roots:
            result[distribution] = roots
    return result


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
    for distribution, roots in _optional_distribution_roots().items():
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


def _startup_modules(service: dict) -> tuple[str, ...]:
    """The modules a container starts: its worker settings, else the CLI's server."""
    command = service.get("command")
    if command:
        return (command[0].rpartition(".")[0],)
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    script_module = pyproject["project"]["scripts"]["songmaker"].partition(":")[0]
    return (script_module, WEB_SERVER_MODULE)


def _installing_containers() -> dict[str, ContainerSpec]:
    """Every compose service built from a Dockerfile that runs ``uv sync`` and starts
    through its command or the image's server; an ``entrypoint`` override starts
    something else, so it names no startup modules here."""
    containers: dict[str, ContainerSpec] = {}
    for name, service in _raw_compose_services().items():
        build = service.get("build")
        if not isinstance(build, dict) or "entrypoint" in service:
            continue
        dockerfile = Path(build["dockerfile"])
        sync_extras = _sync_extras(REPOSITORY_ROOT / dockerfile)
        if not sync_extras:
            continue
        containers[name] = ContainerSpec(
            sync_extras[0], _startup_modules(service),
        )
    return containers


CONTAINERS = _installing_containers()


def test_every_uv_sync_line_of_a_dockerfile_installs_the_same_extras() -> None:
    for name, service in _raw_compose_services().items():
        build = service.get("build")
        if not isinstance(build, dict):
            continue
        sync_extras = _sync_extras(REPOSITORY_ROOT / build["dockerfile"])
        assert all(extras == sync_extras[0] for extras in sync_extras), (
            f"{name}: {build['dockerfile']} installs different extras on its uv sync lines"
        )


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


def test_container_entrypoints_do_not_import_omitted_optional_dependencies() -> None:
    assert CONTAINERS, "_installing_containers derived no container from compose"
    root_owners = _root_owning_extras()
    for name, spec in CONTAINERS.items():
        blocked_roots = frozenset(
            root for root, owners in root_owners.items() if not owners & spec.extras
        )
        completed = _import_startup_modules(spec, blocked_roots)
        assert completed.returncode == 0, (
            f"{name} imported an omitted optional dependency.\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def test_the_mcp_server_spec_imports_without_the_mcp_extra() -> None:
    """The scoring-worker container installs no ``mcp`` extra, so songmaker's
    MCP declaration must stay outside ``mcp_server/`` — whose ``__init__``
    imports that extra eagerly (ruling ac on #825)."""
    spec = CONTAINERS[SCORING_WORKER_SERVICE]
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
    spec = CONTAINERS[SCORING_WORKER_SERVICE]
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


AGENT_CLI_MOUNT_ROOTS = (Path("/home/songmaker"), Path("/usr/local"))


def _short_volume_source_and_target(service_name: str, volume: str) -> tuple[str, str]:
    source, *rest = volume.split(":")
    assert rest, (
        f"{service_name} declares the anonymous volume {volume!r}; "
        f"mount a declared named volume instead"
    )
    return source, posixpath.normpath(rest[0])


def test_check_agent_cli_mounts_rejects_short_syntax_and_host_profiles() -> None:
    services = _raw_compose_services()
    declared_named_volumes = _declared_named_volumes()

    for service_name, service in services.items():
        assert isinstance(service, dict)
        assert "extends" not in service, (
            f"{service_name} must not inherit mounts through Compose extends"
        )
        assert "volumes_from" not in service, (
            f"{service_name} must not inherit mounts through Compose volumes_from"
        )
        volumes = service.get("volumes", [])
        assert isinstance(volumes, list)
        bind_mounts: list[dict[str, object]] = []
        for volume in volumes:
            if isinstance(volume, str):
                source, target = _short_volume_source_and_target(service_name, volume)
                if any(Path(target).is_relative_to(root) for root in AGENT_CLI_MOUNT_ROOTS):
                    assert source in declared_named_volumes, (
                        f"{service_name} must mount {target!r} through Compose "
                        f"long syntax (read-only, no host path creation) or a "
                        f"declared named volume: {volume!r}"
                    )
                assert source in declared_named_volumes or (
                    source.startswith("./") and ".." not in Path(source).parts
                ), (
                    f"{service_name} must use Compose long syntax for every host "
                    f"bind mount so its read-only and host-path protections are "
                    f"explicit: {volume!r} is neither a declared named volume nor "
                    f"a repository-relative path"
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

        for mount in bind_mounts:
            source = mount.get("source")
            assert isinstance(source, str)
            assert "~/.claude" not in source
            assert "~/.claude.json" not in source
            assert "~/.codex" not in source
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
