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
        frozenset({"server", "mcp"}),
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
    assert all("claude" not in spec.extras for spec in CONTAINERS.values())
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


def test_claude_api_key_without_sdk_is_honestly_unavailable_in_web_container() -> None:
    spec = CONTAINERS["web"]
    script = """
from songmaker_cli.cowriter.catalog import (
    DependencyUnavailableProvider,
    get_provider_configuration,
    list_provider_models,
)
from songmaker_cli.cowriter.errors import ProviderUnavailableError

configuration = get_provider_configuration("claude")
assert configuration == DependencyUnavailableProvider("claude", "anthropic")
try:
    list_provider_models("claude")
except ProviderUnavailableError as error:
    assert "required dependency 'anthropic'" in str(error)
else:
    raise AssertionError("missing Claude SDK was accepted")
"""
    blocked_roots = frozenset(
        root for root, owners in _root_owning_extras().items()
        if not owners & spec.extras
    )
    assert "anthropic" in blocked_roots
    completed = _run_with_blocked_optional_imports(
        spec,
        blocked_roots,
        script,
        {"ANTHROPIC_API_KEY": "packaging-boundary-test"},
    )
    assert completed.returncode == 0, (
        f"web ({spec.entrypoint}) did not report the omitted Claude SDK.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
