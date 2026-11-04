"""Behavioural tests for scripts/secret_files.py, driven as a real subprocess.

The command runs from a scratch project root holding it and the shared ``.env``
reader. A fake ``docker`` stands first on PATH and prints a canned
``compose config`` JSON, which also carries distinctive values under
``services.*.environment``: compose's interpolated configuration is exactly
where a leak would come from. Every run gets an explicit environment (a scratch
HOME, no inherited table key), and every run is checked for a leaked value.
"""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import secret_files  # noqa: E402 - needs SCRIPTS on sys.path first

COMMAND_FILES = ("secret_files.py", "dotenv_file.py")

DIRECTORY_MODE = 0o700
FILE_MODE = 0o644
CONFIG_LEAK_VALUE = "fake-config-environment-leak-4d1c"
VALUES = {
    "SESSION_SECRET": "fake-session-value-a1b2",
    "POSTGRES_PASSWORD": "fake-postgres-value-c3d4",
    "SONGMAKER_INTERNAL_TOKEN": "fake-internal-value-e5f6",
    "SONGMAKER_MONITORING_TOKEN": "fake-monitoring-value-g7h8",
    "HF_TOKEN": "fake-hf-value-i9j0",
}
FILE_OF_KEY = {entry.key: entry.name for entry in secret_files.TABLE}
OTHER_VALUE = "fake-other-value-z9y8"
EVERY_VALUE = (*VALUES.values(), CONFIG_LEAK_VALUE, OTHER_VALUE)


@dataclass
class Project:
    root: Path
    home: Path
    bin: Path

    @property
    def default_directory(self) -> Path:
        return self.home / secret_files.DEFAULT_DIRECTORY

    def write_env(self, assignments: dict[str, str]) -> None:
        (self.root / ".env").write_text(
            "".join(f"{key}={value}\n" for key, value in assignments.items()),
        )

    def declare(self, files: dict[str, Path], exit_code: int = 0) -> None:
        """Make the fake ``compose config`` declare these secret files."""
        config = {
            "services": {"web": {"environment": {"LEAK": CONFIG_LEAK_VALUE}}},
            "secrets": {name: {"file": str(path)} for name, path in files.items()},
        }
        (self.bin / "config.json").write_text(json.dumps(config))
        (self.bin / "exit_code").write_text(str(exit_code))

    def declare_table_files(self, directory: Path | None = None) -> None:
        directory = directory or self.default_directory
        self.declare({name: directory / name for name in FILE_OF_KEY.values()})

    def put_file(self, name: str, content: str, directory: Path | None = None) -> Path:
        directory = directory or self.default_directory
        directory.mkdir(parents=True, exist_ok=True, mode=DIRECTORY_MODE)
        directory.chmod(DIRECTORY_MODE)
        path = directory / name
        path.write_text(content)
        return path

    def run(
        self, *arguments: str, environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(self.root / "scripts" / "secret_files.py"), *arguments],
            cwd=self.root,
            env={
                "PATH": f"{self.bin}:/usr/bin:/bin",
                "HOME": str(self.home),
                **(environment or {}),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        for value in EVERY_VALUE:
            assert value not in result.stdout, "a value reached stdout"
            assert value not in result.stderr, "a value reached stderr"
        return result


@pytest.fixture
def project(tmp_path: Path) -> Project:
    (tmp_path / "scripts").mkdir()
    for name in COMMAND_FILES:
        shutil.copy(SCRIPTS / name, tmp_path / "scripts" / name)
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    docker = bin_directory / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        f'[ "$*" = "compose config --format json" ] || exit 64\n'
        f'cat "{bin_directory}/config.json"\n'
        f'exit "$(cat "{bin_directory}/exit_code")"\n',
    )
    docker.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    scratch = Project(tmp_path, home, bin_directory)
    scratch.declare({})
    return scratch


def test_copy_writes_each_value_byte_exact_and_leaves_the_env_untouched(project: Project) -> None:
    project.write_env(VALUES)
    env_before = (project.root / ".env").read_bytes()

    result = project.run()

    assert result.returncode == 0, result.stderr
    directory = project.default_directory
    assert stat.S_IMODE(directory.stat().st_mode) == DIRECTORY_MODE
    for key, value in VALUES.items():
        written = directory / FILE_OF_KEY[key]
        assert written.read_bytes() == value.encode()
        assert stat.S_IMODE(written.stat().st_mode) == FILE_MODE
    assert sorted(path.name for path in directory.iterdir()) == sorted(FILE_OF_KEY.values())
    assert (project.root / ".env").read_bytes() == env_before


def test_copy_skips_a_key_absent_from_the_env_and_names_it(project: Project) -> None:
    project.write_env({key: value for key, value in VALUES.items() if key != "HF_TOKEN"})

    result = project.run()

    assert result.returncode == 0, result.stderr
    assert "HF_TOKEN" in result.stdout
    assert not (project.default_directory / "hf-token").exists()


def test_a_second_copy_changes_nothing(project: Project) -> None:
    project.write_env(VALUES)
    project.run()
    written = project.default_directory / "session-secret"
    inode_before = written.stat().st_ino

    result = project.run()

    assert result.returncode == 0, result.stderr
    assert written.stat().st_ino == inode_before


def test_a_file_differing_only_by_surrounding_whitespace_counts_as_copied(project: Project) -> None:
    project.write_env(VALUES)
    written = project.put_file("session-secret", f" {VALUES['SESSION_SECRET']}\n")

    result = project.run()

    assert result.returncode == 0, result.stderr
    assert written.read_text() == f" {VALUES['SESSION_SECRET']}\n"


def test_copy_refuses_to_overwrite_a_differing_file_and_writes_nothing(project: Project) -> None:
    project.write_env(VALUES)
    differing = project.put_file("postgres-password", OTHER_VALUE)

    result = project.run()

    assert result.returncode != 0
    assert "postgres-password" in result.stderr
    assert "POSTGRES_PASSWORD" in result.stderr
    assert differing.read_text() == OTHER_VALUE
    assert not (project.default_directory / "session-secret").exists()


def test_copy_refuses_a_key_exported_with_another_value(project: Project) -> None:
    project.write_env(VALUES)

    result = project.run(environment={"SESSION_SECRET": OTHER_VALUE})

    assert result.returncode != 0
    assert "SESSION_SECRET" in result.stderr
    assert not project.default_directory.exists()


def test_copy_refuses_a_missing_env_file(project: Project) -> None:
    result = project.run()

    assert result.returncode != 0
    assert ".env" in result.stderr


def test_copy_refuses_a_directory_with_a_loose_mode(project: Project) -> None:
    project.write_env(VALUES)
    project.put_file("unrelated", "x")
    project.default_directory.chmod(0o755)

    result = project.run()

    assert result.returncode != 0
    assert str(project.default_directory) in result.stderr
    assert not (project.default_directory / "session-secret").exists()


def test_copy_refuses_a_path_that_is_not_a_directory(project: Project) -> None:
    project.write_env(VALUES)
    project.default_directory.parent.mkdir()
    project.default_directory.write_text("a file")

    result = project.run()

    assert result.returncode != 0
    assert str(project.default_directory) in result.stderr


def test_copy_refuses_an_unquotable_env_value_naming_only_the_key(project: Project) -> None:
    project.write_env({"SESSION_SECRET": "$interpolated-fake-value"})

    result = project.run()

    assert result.returncode != 0
    assert "SESSION_SECRET" in result.stderr
    assert "interpolated-fake-value" not in result.stderr


@pytest.mark.parametrize(
    ("exported", "in_env_file", "expected_relative"),
    [
        pytest.param("/exported/dir", "/from/env/file", "/exported/dir", id="exported-wins"),
        pytest.param("", "/from/env/file", None, id="exported-empty-takes-the-default"),
        pytest.param(None, "/from/env/file", "/from/env/file", id="env-file"),
        pytest.param(None, None, None, id="default"),
        pytest.param("~/under-home", None, "HOME/under-home", id="tilde"),
    ],
)
def test_the_directory_resolves_exported_then_env_file_then_default(
    project: Project, exported: str | None, in_env_file: str | None, expected_relative: str | None,
) -> None:
    def placed(path: str) -> str:
        return str(project.root / path.lstrip("/")) if path.startswith("/") else path

    assignments = dict(VALUES)
    if in_env_file is not None:
        assignments["SONGMAKER_SECRETS_DIR"] = placed(in_env_file)
    project.write_env(assignments)
    environment = {} if exported is None else {"SONGMAKER_SECRETS_DIR": placed(exported)}
    if expected_relative is None:
        expected = project.default_directory
    elif expected_relative.startswith("HOME/"):
        expected = project.home / expected_relative.removeprefix("HOME/")
    else:
        expected = Path(placed(expected_relative))

    result = project.run(environment=environment)

    assert result.returncode == 0, result.stderr
    assert (expected / "session-secret").read_text() == VALUES["SESSION_SECRET"]


@pytest.mark.parametrize("bad", ["relative/dir", "~other/dir", "./here"])
def test_a_directory_that_is_neither_absolute_nor_under_home_is_refused(
    project: Project, bad: str,
) -> None:
    project.write_env(VALUES)

    result = project.run(environment={"SONGMAKER_SECRETS_DIR": bad})

    assert result.returncode != 0
    assert "SONGMAKER_SECRETS_DIR" in result.stderr


def test_verify_passes_when_compose_declares_none_of_the_files(project: Project) -> None:
    project.write_env(VALUES)

    result = project.run("--verify")

    assert result.returncode == 0, result.stderr


def test_verify_passes_after_a_copy(project: Project) -> None:
    project.write_env(VALUES)
    project.run()
    project.declare_table_files()

    result = project.run("--verify")

    assert result.returncode == 0, result.stderr


def test_verify_passes_for_an_empty_optional_file_and_ignores_surrounding_whitespace(
    project: Project,
) -> None:
    project.write_env({**VALUES, "HF_TOKEN": ""})
    project.run()
    project.put_file("postgres-password", f"\n{VALUES['POSTGRES_PASSWORD']}  \n")
    project.declare_table_files()

    result = project.run("--verify")

    assert result.returncode == 0, result.stderr


def test_verify_refuses_a_missing_file(project: Project) -> None:
    project.write_env(VALUES)
    project.declare_table_files()

    result = project.run("--verify")

    assert result.returncode != 0
    assert "session-secret" in result.stderr


@pytest.mark.parametrize("blank", ["", "  \n\t\n"], ids=["empty", "whitespace-only"])
def test_verify_refuses_a_blank_non_optional_file(project: Project, blank: str) -> None:
    project.write_env({})
    project.put_file("internal-token", blank)
    project.declare({"internal-token": project.default_directory / "internal-token"})

    result = project.run("--verify")

    assert result.returncode != 0
    assert "internal-token" in result.stderr


def test_verify_refuses_a_file_differing_from_a_key_still_in_the_env(project: Project) -> None:
    project.write_env(VALUES)
    project.put_file("session-secret", OTHER_VALUE)
    project.declare({"session-secret": project.default_directory / "session-secret"})

    result = project.run("--verify")

    assert result.returncode != 0
    assert "session-secret" in result.stderr
    assert "SESSION_SECRET" in result.stderr


def test_verify_accepts_a_file_whose_key_left_the_env(project: Project) -> None:
    project.write_env({})
    project.put_file("session-secret", OTHER_VALUE)
    project.declare({"session-secret": project.default_directory / "session-secret"})

    result = project.run("--verify")

    assert result.returncode == 0, result.stderr


def test_verify_refuses_a_key_exported_with_another_value(project: Project) -> None:
    project.write_env(VALUES)
    project.run()
    project.declare_table_files()

    result = project.run("--verify", environment={"HF_TOKEN": OTHER_VALUE})

    assert result.returncode != 0
    assert "HF_TOKEN" in result.stderr


def test_verify_refuses_an_unknown_file_in_the_directory(project: Project) -> None:
    project.write_env(VALUES)
    unknown = project.put_file("surprise-token", OTHER_VALUE)
    project.declare({"surprise": unknown})

    result = project.run("--verify")

    assert result.returncode != 0
    assert "surprise-token" in result.stderr


def test_verify_refuses_a_table_file_resolved_outside_the_directory(project: Project) -> None:
    project.write_env(VALUES)
    elsewhere = project.root / "elsewhere"
    project.put_file("session-secret", VALUES["SESSION_SECRET"], directory=elsewhere)
    project.declare({"session-secret": elsewhere / "session-secret"})

    result = project.run("--verify")

    assert result.returncode != 0
    assert str(elsewhere) in result.stderr
    assert str(project.default_directory) in result.stderr


def test_a_failing_config_is_refused_naming_only_its_exit_code(project: Project) -> None:
    project.declare_table_files()
    project.declare({"session-secret": project.default_directory / "session-secret"}, exit_code=3)

    result = project.run("--verify")

    assert result.returncode != 0
    assert "3" in result.stderr
    assert "session-secret" not in result.stderr


def test_an_unparsable_config_is_refused(project: Project) -> None:
    (project.bin / "config.json").write_text(f"not json {CONFIG_LEAK_VALUE}")

    result = project.run("--verify")

    assert result.returncode != 0
    assert "no readable secrets block" in result.stderr
    assert "Traceback" not in result.stderr


def test_verify_refuses_naming_docker_when_docker_cannot_be_run(project: Project) -> None:
    project.write_env(VALUES)

    result = project.run("--verify", environment={"PATH": "/nonexistent"})

    assert result.returncode != 0
    assert "docker" in result.stderr
    assert "Traceback" not in result.stderr


def test_copy_needs_no_docker(project: Project) -> None:
    project.write_env(VALUES)

    result = project.run(environment={"PATH": "/nonexistent"})

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mode", ["copy", "verify"])
def test_a_non_utf8_env_is_refused_without_a_traceback_or_a_byte(
    project: Project, mode: str,
) -> None:
    (project.root / ".env").write_bytes(b"SESSION_SECRET=\xffsecret-tail\n")
    project.declare_table_files()

    result = project.run(*(["--verify"] if mode == "verify" else []))

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "\\xff" not in result.stderr
    assert "secret-tail" not in result.stderr
    assert "cannot read" in result.stderr


def test_copy_refuses_a_value_with_surrounding_whitespace_naming_the_key(
    project: Project,
) -> None:
    project.write_env({**VALUES, "SESSION_SECRET": f"\" {VALUES['SESSION_SECRET']}\""})

    result = project.run()

    assert result.returncode != 0
    assert "SESSION_SECRET" in result.stderr
    assert not project.default_directory.exists()


def test_copy_refuses_a_symlinked_table_file_and_verify_does_too(project: Project) -> None:
    project.write_env(VALUES)
    outside = project.put_file(
        "session-secret", VALUES["SESSION_SECRET"], directory=project.root / "outside",
    )
    directory = project.default_directory
    directory.mkdir(parents=True, mode=DIRECTORY_MODE)
    (directory / "session-secret").symlink_to(outside)
    project.declare({"session-secret": directory / "session-secret"})

    copied = project.run()
    verified = project.run("--verify")

    for result in (copied, verified):
        assert result.returncode != 0
        assert "session-secret" in result.stderr
        assert "symbolic link" in result.stderr


@pytest.mark.parametrize("mode", ["copy", "verify"])
def test_a_symlinked_secrets_directory_is_refused(project: Project, mode: str) -> None:
    project.write_env(VALUES)
    real = project.root / "real"
    real.mkdir(mode=DIRECTORY_MODE)
    (real / "session-secret").write_text(VALUES["SESSION_SECRET"])
    project.default_directory.parent.mkdir(parents=True)
    project.default_directory.symlink_to(real)
    project.declare({"session-secret": project.default_directory / "session-secret"})

    result = project.run(*(["--verify"] if mode == "verify" else []))

    assert result.returncode != 0
    assert "symbolic link" in result.stderr or "must be a directory" in result.stderr


def test_copy_refuses_when_the_directory_cannot_be_created(project: Project) -> None:
    project.write_env(VALUES)
    project.default_directory.parent.write_text("a file where the parent should be")

    result = project.run()

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "cannot" in result.stderr


def test_publishing_never_replaces_a_file_that_appeared_meanwhile(tmp_path: Path) -> None:
    """Unit test of the publish function; a subprocess run has no seam between check and write."""
    target = tmp_path / "session-secret"
    target.write_text("other-value-from-the-race")

    with pytest.raises(secret_files.Refusal):
        secret_files._publish(target, "wanted-value")

    assert target.read_text() == "other-value-from-the-race"
    assert [path.name for path in tmp_path.iterdir()] == ["session-secret"]


def test_publishing_beside_an_equal_file_that_appeared_meanwhile_is_a_no_op(
    tmp_path: Path,
) -> None:
    target = tmp_path / "session-secret"
    target.write_text("wanted-value\n")

    secret_files._publish(target, "wanted-value")

    assert target.read_text() == "wanted-value\n"
    assert [path.name for path in tmp_path.iterdir()] == ["session-secret"]


def test_a_failing_cleanup_of_the_temporary_file_is_a_refusal_naming_no_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "session-secret"
    target.write_bytes(b"\xffcontent-byte")

    def failing_unlink(self: Path, missing_ok: bool = False) -> None:
        raise PermissionError("content-byte")

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(secret_files.Refusal) as refusal:
        secret_files._publish(target, "wanted-value")

    assert "content-byte" not in str(refusal.value)
    assert refusal.value.__suppress_context__
    assert refusal.value.__cause__ is None


def test_an_unexpected_error_prints_one_fixed_line_naming_only_its_type(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def explode(*_arguments: object) -> None:
        raise ValueError("embedded null byte secret-message")

    monkeypatch.setattr(secret_files, "copy", explode)

    exit_code = secret_files.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err.count("\n") == 1
    assert "ValueError" in captured.err
    assert "secret-message" not in captured.err + captured.out


@pytest.mark.parametrize("appears_as", ["loose directory", "symlink"])
def test_a_directory_appearing_after_the_prechecks_is_validated_before_any_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, appears_as: str,
) -> None:
    """Unit test of copy: a subprocess run has no seam between the prechecks and the publish."""
    for key in (*FILE_OF_KEY, secret_files.DIRECTORY_KEY):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / ".env").write_text(f"SESSION_SECRET={VALUES['SESSION_SECRET']}\n")
    home = tmp_path / "home"
    directory = home / secret_files.DEFAULT_DIRECTORY
    original = secret_files._require_private_directory

    def check_then_let_the_directory_appear(checked: Path) -> None:
        original(checked)
        if appears_as == "symlink":
            (tmp_path / "elsewhere").mkdir(mode=DIRECTORY_MODE)
            checked.parent.mkdir(parents=True, exist_ok=True)
            checked.symlink_to(tmp_path / "elsewhere")
        else:
            checked.mkdir(parents=True, mode=0o777)
            checked.chmod(0o777)

    monkeypatch.setattr(
        secret_files, "_require_private_directory", check_then_let_the_directory_appear,
    )

    with pytest.raises(secret_files.Refusal) as refusal:
        secret_files.copy(tmp_path, home)

    assert str(directory) in str(refusal.value)
    assert list(directory.iterdir()) == []
