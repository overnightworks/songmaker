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
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from support.compose_config import run_compose_config
from support.dockerfile_stages import dockerfile_instructions, final_stage_instructions
from support.repository_root import REPOSITORY_ROOT

from songmaker_cli.settings import Settings

SOURCE_ROOT = REPOSITORY_ROOT / "src"
DOCKER_ROOT = REPOSITORY_ROOT / "docker"
UV_INSTALLED_ENVIRONMENT_FLAGS = frozenset({"--no-sync", "--frozen", "--no-build"})
IMAGE_VIRTUALENV_BIN = "/app/.venv/bin/"
WEB_ENTRYPOINT_SCRIPT = "/app/start_web_server.sh"
E2E_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "e2e.yml"
TEST_STACK_COMPOSE_FILE = DOCKER_ROOT / "docker-compose.test.yml"
DOCKER_DEFAULT_RESTART_POLICY = "no"
WEB_SERVER_MODULE = "songmaker_cli.server"
RECURSIVE_CHOWN = re.compile(r"\bchown(?:\s+-\S+)*?\s+(?:-\w*R\w*|--recursive)\b")


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
            if distribution in {canonicalize_name(owner) for owner in owners}
        )
        if roots:
            result[distribution] = roots
    return result


def _core_distributions() -> frozenset[str]:
    pyproject = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())
    return frozenset(
        canonicalize_name(Requirement(requirement).name)
        for requirement in pyproject["project"]["dependencies"]
    )


def _optional_extras_by_distribution() -> dict[str, frozenset[str]]:
    """Map every genuinely optional distribution to the extras that install it.

    A core requirement is installed everywhere, so naming it in an extra does
    not make it omittable; `songmaker[signal]` installs that extra's members.
    """
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text())["project"]
    project_name = canonicalize_name(project["name"])
    declared = project["optional-dependencies"]

    def installed_by(extra: str, path: frozenset[str]) -> set[str]:
        found: set[str] = set()
        for requirement in map(Requirement, declared[extra]):
            name = canonicalize_name(requirement.name)
            included_extras = requirement.extras if name == project_name else frozenset()
            found.add(name)
            for included in included_extras - path:
                found |= installed_by(included, path | {included})
        return found - {project_name}

    result: dict[str, set[str]] = {}
    for extra in declared:
        for distribution in installed_by(extra, frozenset({extra})) - _core_distributions():
            result.setdefault(distribution, set()).add(extra)
    return {distribution: frozenset(extras) for distribution, extras in result.items()}


def _root_owning_extras() -> dict[str, frozenset[str]]:
    extras_by_distribution = _optional_extras_by_distribution()
    result: dict[str, set[str]] = {}
    for distribution, roots in _optional_distribution_roots().items():
        for root in roots:
            result.setdefault(root, set()).update(extras_by_distribution[distribution])
    return {root: frozenset(extras) for root, extras in result.items()}


def _sync_extras(dockerfile: Path) -> list[frozenset[str]]:
    return [
        frozenset(re.findall(r"--extra\s+([A-Za-z0-9-]+)", instruction))
        for instruction in final_stage_instructions(dockerfile)
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
    compose = yaml.load(path.read_text(), Loader=_ComposeLoader)  # noqa: S506 - _ComposeLoader extends SafeLoader and safe_load cannot take the merge tags
    assert isinstance(compose, dict)
    return compose


def _raw_compose() -> dict[str, object]:
    return _compose_file(TEST_STACK_COMPOSE_FILE)


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


def _compose_file_arguments(compose_arguments: tuple[str, ...]) -> tuple[str, ...]:
    """The files a Compose command line names, whatever other options it carries."""
    return tuple(
        argument
        for flag, argument in itertools.pairwise(compose_arguments)
        if flag in ("-f", "--file")
    )


def _test_stacks() -> dict[str, tuple[str, ...]]:
    workflow_files = _e2e_workflow_compose_files()
    return {
        "e2e-workflow": workflow_files,
        "voices-e2e": (*workflow_files, "-f", "docker/docker-compose.e2e-voices.yml"),
    }


TEST_STACKS = _test_stacks()
# The files e2e.yml's "Write the throwaway secret files" step writes at run time.
E2E_WORKFLOW_SECRET_PATHS = {
    "SONGMAKER_SECRETS_DIR": "/scratch/songmaker-secrets",
    "KEYCLOAK_CLIENT_SECRET_FILE": "/scratch/keycloak-client-secret",
    "GATEWAY_KEY_FILE": "/scratch/gateway-key",
}


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
        environment={
            **_e2e_workflow_environment(),
            **E2E_WORKFLOW_SECRET_PATHS,
            **dict(operator_environment),
        },
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


def _compose_built_dockerfiles() -> dict[str, Path]:
    dockerfiles: dict[str, Path] = {}
    for name, service in _raw_compose_services().items():
        build = service.get("build")
        if isinstance(build, dict):
            dockerfiles[name] = REPOSITORY_ROOT / build["dockerfile"]
    return dockerfiles


def _image_identity(dockerfile: Path) -> tuple[str, set[str]]:
    """The final ``USER`` as ``uid:gid`` plus every ``uid:gid`` the file creates."""
    final_users = [
        instruction.split(maxsplit=1)[1]
        for instruction in final_stage_instructions(dockerfile)
        if instruction.upper().startswith("USER ")
    ]
    instructions = " ".join(dockerfile_instructions(dockerfile))
    created_gids = re.findall(r"groupadd\s+--gid\s+(\d+)", instructions)
    created_users = re.findall(r"useradd\s+--uid\s+(\d+)\s+--gid\s+(\d+)", instructions)
    assert final_users, f"{dockerfile.name}: no USER in the final stage"
    assert created_gids, f"{dockerfile.name}: no numeric groupadd"
    assert created_users, f"{dockerfile.name}: no numeric useradd"
    assert len(created_gids) == instructions.count("groupadd"), (
        f"{dockerfile.name}: a groupadd has no numeric --gid"
    )
    assert len(created_users) == instructions.count("useradd"), (
        f"{dockerfile.name}: a useradd has no numeric --uid and --gid"
    )
    for _, joined_gid in created_users:
        assert joined_gid in created_gids, (
            f"{dockerfile.name}: useradd joins a group other than a groupadd one"
        )
    return final_users[-1], {f"{uid}:{gid}" for uid, gid in created_users}


def test_every_compose_built_image_runs_as_the_numeric_user_it_creates() -> None:
    identities = {
        name: _image_identity(dockerfile)
        for name, dockerfile in _compose_built_dockerfiles().items()
    }
    assert identities
    for name, (final_user, created) in identities.items():
        assert re.fullmatch(r"[1-9]\d*:[1-9]\d*", final_user), (
            f"{name}: final USER {final_user!r} is not a nonzero numeric uid:gid"
        )
        assert created == {final_user}, (
            f"{name}: USER {final_user} differs from created {sorted(created)}"
        )
    assert len({final_user for final_user, _ in identities.values()}) == 1, (
        "images share volumes, so they must share one uid:gid"
    )


@pytest.mark.parametrize(
    "instruction",
    [
        "RUN chown -R songmaker:songmaker /app",
        "RUN chown -f -R songmaker:songmaker /app",
        "RUN chown --verbose --recursive songmaker:songmaker /app",
    ],
)
def test_recursive_chown_is_found_after_other_options(instruction: str) -> None:
    assert RECURSIVE_CHOWN.search(instruction)


def test_no_final_stage_instruction_changes_ownership_recursively() -> None:
    offenders = [
        instruction
        for instruction in final_stage_instructions(REPOSITORY_ROOT / "Dockerfile")
        if RECURSIVE_CHOWN.search(instruction)
    ]

    assert offenders == []


def _command_words(declaration: str | list[str]) -> tuple[str, ...]:
    if isinstance(declaration, list):
        return tuple(declaration)
    if declaration.startswith("["):
        return tuple(json.loads(declaration))
    return tuple(shlex.split(declaration))


def _relative(path: Path) -> str:
    return str(path.relative_to(REPOSITORY_ROOT))


def _compose_entrypoint_starts() -> list[ContainerStart]:
    compose_files = sorted(DOCKER_ROOT.glob("docker-compose*.yml"))
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
        for instruction in dockerfile_instructions(dockerfile)
        if instruction.startswith("ENTRYPOINT ")
    ]


def _entrypoint_script_starts() -> list[ContainerStart]:
    starts = [
        ContainerStart(f"{_relative(script)}::exec", tuple(shlex.split(line)[1:]))
        for script in sorted(DOCKER_ROOT.rglob("*.sh"))
        for line in script.read_text().splitlines()
        if line.strip().startswith("exec ")
    ]
    assert starts, "found no exec line in any script under docker/"
    return starts


def _repo_built_container_starts() -> list[ContainerStart]:
    return [
        *_compose_entrypoint_starts(),
        *_dockerfile_entrypoint_starts(),
        *_entrypoint_script_starts(),
    ]


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


AGENT_CLI_MOUNT_ROOTS = (Path("/home/songmaker"), Path("/usr/local"))


def _short_volume_source_and_target(service_name: str, volume: str) -> tuple[str, str]:
    source, *rest = volume.split(":")
    assert rest, (
        f"{service_name} declares the anonymous volume {volume!r}; "
        f"mount a declared named volume instead"
    )
    return source, str(_as_linux_resolves(rest[0]))


def test_check_agent_cli_mounts_rejects_short_syntax_and_host_profiles() -> None:
    services = _raw_compose_services()
    declared_named_volumes = _declared_named_volumes()

    for service_name, service in services.items():
        assert isinstance(service, dict)
        inheritance = "inherit mounts through Compose"
        assert "extends" not in service, f"{service_name} must not {inheritance} extends"
        assert "volumes_from" not in service, f"{service_name} must not {inheritance} volumes_from"
        volumes = service.get("volumes", [])
        assert isinstance(volumes, list)
        bind_mounts: list[dict[str, object]] = []
        for volume in volumes:
            if isinstance(volume, str):
                source, target = _short_volume_source_and_target(service_name, volume)
                if any(Path(target).is_relative_to(root) for root in AGENT_CLI_MOUNT_ROOTS):
                    assert source in declared_named_volumes, (
                        f"{service_name} must mount {target!r} through Compose long syntax "
                        f"(read-only, no host path creation) or a declared named volume: {volume!r}"
                    )
                assert source in declared_named_volumes or (
                    source.startswith("./") and ".." not in Path(source).parts
                ), (
                    f"{service_name} must use Compose long syntax for every host bind mount so "
                    f"its read-only and host-path protections are explicit: {volume!r} is "
                    f"neither a declared named volume nor a repository-relative path"
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


CONTAINER_HOME = Path("/home/songmaker")
MIRROR_DIRECTORY_MARKER = "agent-cli-credentials"
EVERY_COMPOSE_FILE = tuple(
    REPOSITORY_ROOT / name
    for name in subprocess.check_output(
        ["git", "ls-files"], cwd=REPOSITORY_ROOT, text=True
    ).splitlines()
    if re.search(r"(^|/)(docker-)?compose[^/]*\.ya?ml$", name)
)


def _as_linux_resolves(path: str) -> Path:
    return Path(posixpath.normpath(re.sub(r"^/+", "/", path)))


def _agent_login_binds(services: dict[str, dict]) -> list[str]:
    """Binds of rendered services; Compose prints every volume in long form."""
    offences = []
    for service_name, service in services.items():
        for volume in service.get("volumes", []):
            if volume["type"] != "bind":
                continue
            source, target = volume["source"], volume["target"]
            if MIRROR_DIRECTORY_MARKER in source or any(
                _as_linux_resolves(path).is_relative_to(CONTAINER_HOME) for path in (source, target)
            ):
                offences.append(f"{service_name} binds {source} to {target}")
    return offences


def _render_services(compose_args: tuple[str, ...], env_file: Path) -> dict[str, dict]:
    rendered = run_compose_config(
        (*compose_args, "-p", "songmaker-packaging-boundary-test", "--profile", "*"),
        ("--format", "json"),
        env_file=env_file,
        environment={},
    )
    assert rendered.returncode == 0, rendered.stderr
    return json.loads(rendered.stdout)["services"]


@pytest.mark.parametrize("stack", TEST_STACKS, ids=str)
def test_no_stack_binds_an_agent_cli_or_a_login(stack: str) -> None:
    services = _rendered_test_stack_services(TEST_STACKS[stack])

    assert _agent_login_binds(services) == []


def test_every_compose_file_belongs_to_a_rendered_stack() -> None:
    rendered = {
        (REPOSITORY_ROOT / name).resolve()
        for files in TEST_STACKS.values()
        for name in _compose_file_arguments(files)
    }
    assert {path.resolve() for path in EVERY_COMPOSE_FILE} <= rendered


_HOME_AUTH = "/home/songmaker/.grok/auth.json"
_MIRROR = "/x/agent-cli-credentials"
AGENT_LOGIN_BIND_FIXTURES = {
    "long-target-under-home": (
        f"{{type: bind, source: /srv/a, target: {_HOME_AUTH}}}", f"/srv/a to {_HOME_AUTH}"),
    "long-source-under-home": (
        "{type: bind, source: /home/songmaker/c, target: /c}", "/home/songmaker/c to /c"),
    "long-source-with-two-leading-slashes": (
        "{type: bind, source: //home/songmaker/c, target: /c}", "//home/songmaker/c to /c"),
    "long-source-from-mirror-directory": (
        f"{{type: bind, source: '${{DIR:-{_MIRROR}}}/c.json', target: /c.json}}",
        f"{_MIRROR}/c.json to /c.json",
    ),
    "short-target-under-home": (f"/srv/a:{_HOME_AUTH}:ro", f"/srv/a to {_HOME_AUTH}"),
    "short-source-under-home": (f"{_HOME_AUTH}:/auth.json", f"{_HOME_AUTH} to /auth.json"),
    "short-source-from-mirror-directory": (f"'${{DIR:-{_MIRROR}}}/c:/c'", f"{_MIRROR}/c to /c"),
    "short-nested-default-target": (
        f"/srv/a:${{A:-${{B:-{_HOME_AUTH}}}}}:ro", f"/srv/a to {_HOME_AUTH}"),
    "dotdot-source-into-home": ("/a/../home/songmaker/c:/c", "/a/../home/songmaker/c to /c"),
    "short-dash-default-target": (f"'/srv/a:${{X-{_HOME_AUTH}}}:ro'", f"/srv/a to {_HOME_AUTH}"),
}


@pytest.mark.parametrize(
    ("volume", "bind"), AGENT_LOGIN_BIND_FIXTURES.values(), ids=AGENT_LOGIN_BIND_FIXTURES.keys()
)
def test_the_agent_login_bind_check_names_the_service_and_the_bind(
    volume: str, bind: str, tmp_path: Path
) -> None:
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        f"services:\n  songmaker-web:\n    image: scratch\n    volumes:\n      - {volume}\n"
    )

    services = _render_services(("-f", str(compose_file)), Path(os.devnull))

    assert _agent_login_binds(services) == [f"songmaker-web binds {bind}"]


CONFINEMENT_REPLACING_OPTIONS = ("seccomp", "apparmor", "systempaths")


def _confinement_replacements(services: dict) -> dict[str, str]:
    return {
        service_name: option
        for service_name, service in services.items()
        if isinstance(service, dict)
        for option in service.get("security_opt", [])
        if option.startswith(CONFINEMENT_REPLACING_OPTIONS)
    }


@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
def test_no_test_stack_service_replaces_dockers_default_confinement(
    compose_files: tuple[str, ...],
) -> None:
    assert not _confinement_replacements(_rendered_test_stack_services(compose_files))


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


@pytest.mark.parametrize("secret_name", ["keycloak_client_secret", "gateway_key"])
@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
def test_only_the_web_service_holds_the_secret_the_edge_and_hal_own(
    compose_files: tuple[str, ...], secret_name: str,
) -> None:
    holders = {
        service_name
        for service_name, service in _rendered_test_stack_services(compose_files).items()
        if secret_name in {s["source"] for s in service.get("secrets", [])}
    }
    assert holders == {"songmaker-web"}


@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
def test_the_web_gateway_key_file_is_where_compose_mounts_the_gateway_key(
    compose_files: tuple[str, ...],
) -> None:
    web = _rendered_test_stack_services(compose_files)["songmaker-web"]
    mount_targets = {secret["source"]: secret["target"] for secret in web["secrets"]}
    assert web["environment"]["AGENT__GATEWAY__KEY_FILE"] == mount_targets["gateway_key"]


@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
def test_settings_accept_the_agent_the_web_service_is_rendered_with(
    compose_files: tuple[str, ...], monkeypatch: pytest.MonkeyPatch,
) -> None:
    web_environment = _rendered_test_stack_services(compose_files)["songmaker-web"]["environment"]
    for name, value in web_environment.items():
        if name.startswith("AGENT__"):
            monkeypatch.setenv(name, value)

    settings = Settings(
        _env_file=None, database_url="postgresql://x", redis_url="redis://x",
        session_secret="s", songmaker_internal_token="t",
    )

    assert settings.agent is not None


@pytest.mark.parametrize("compose_files", TEST_STACKS.values(), ids=TEST_STACKS.keys())
def test_only_the_web_app_holds_the_monitoring_token(
    compose_files: tuple[str, ...],
) -> None:
    holders = {
        service_name
        for service_name, service in _rendered_test_stack_services(compose_files).items()
        if "songmaker_monitoring_token" in {s["source"] for s in service.get("secrets", [])}
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
