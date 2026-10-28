"""Behavioral tests for scripts/restore.sh and the retention switch of scripts/backup.sh.

A fake ``docker`` executable is placed first on PATH; it records its arguments
and can be told to fail on a matching command, so no real Docker is touched.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore.sh"
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup.sh"

FAKE_DOCKER = """#!/bin/bash
echo "$*" >> "$FAKE_LOG"
if [[ -n "${FAKE_DOCKER_FAIL_ON:-}" && "$*" == *"$FAKE_DOCKER_FAIL_ON"* ]]; then
    echo "fake docker: refused" >&2
    exit 1
fi
if [[ "$*" == "compose config --images postgres" ]]; then
    echo "helper-image:pinned"
    exit 0
fi
if [[ "$*" == *"find /data -type f"* ]]; then
    seq 1 "${FAKE_VOLUME_FILES:-2}"
fi
"""

FAKE_SYSTEMCTL = """#!/bin/bash
echo "systemctl $*" >> "$FAKE_LOG"
[[ "${FAKE_SYSTEMCTL_BROKEN:-0}" != 1 ]] || exit 1
echo "${FAKE_TIMER_STATE:-inactive}"
"""

FAKE_FLOCK = """#!/bin/bash
echo "flock $*" >> "$FAKE_LOG"
[[ "${FAKE_LOCK_BUSY:-0}" != 1 ]]
"""


@pytest.fixture
def docker_log(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        ("docker", FAKE_DOCKER),
        ("systemctl", FAKE_SYSTEMCTL),
        ("flock", FAKE_FLOCK),
    ):
        fake = bin_dir / name
        fake.write_text(body)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return tmp_path / "docker.log"


def _run(script: Path, docker_log: Path, args: list[str], *, stdin: str = "", **env: str):
    full_env = {
        **os.environ,
        "PATH": f"{docker_log.parent / 'bin'}:{os.environ['PATH']}",
        "FAKE_LOG": str(docker_log),
        "SONGMAKER_AUTODEPLOY_LOCK_FILE": str(docker_log.parent / "autodeploy.lock"),
        **env,
    }
    return subprocess.run(
        ["bash", str(script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=full_env,
        cwd=docker_log.parent,
        check=False,
    )


def _logged(docker_log: Path) -> list[str]:
    return docker_log.read_text().splitlines() if docker_log.exists() else []


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    snap = tmp_path / "snap"
    (snap / "audio").mkdir(parents=True)
    (snap / "audio" / "a.mp3").write_bytes(b"a")
    (snap / "audio" / "b.mp3").write_bytes(b"b")
    (snap / "db.dump").write_bytes(b"dump")
    (snap / "manifest.txt").write_text("timestamp=20260329_030000\naudio_files=2\n")
    return snap


def _index(lines: list[str], needle: str) -> int:
    return next(i for i, line in enumerate(lines) if needle in line)


DESTRUCTIVE_STEPS = [
    "compose stop",
    "DROP DATABASE",
    "--single-transaction",
    "helper-image:pinned sh -c",
]


def test_restore_runs_in_order_and_leaves_writers_stopped(docker_log: Path, snapshot: Path) -> None:
    result = _run(RESTORE_SCRIPT, docker_log, [str(snapshot)], stdin="y\n")

    assert result.returncode == 0, result.stderr
    lines = _logged(docker_log)
    stop = _index(lines, "compose stop")
    for writer in (
        "songmaker-web",
        "songmaker-music-worker",
        "songmaker-acestep-worker-0",
        "songmaker-scoring-worker",
    ):
        assert writer in lines[stop]
    validate = _index(lines, "pg_restore --list")
    recreate = _index(lines, "DROP DATABASE")
    restore = _index(lines, "--single-transaction")
    audio = _index(lines, "helper-image:pinned sh -c")
    assert validate < stop < recreate < restore < audio
    assert "--exit-on-error" in lines[restore]
    assert "WITH (FORCE)" in lines[recreate]
    assert "IF EXISTS" not in lines[recreate]
    assert not any("compose up" in line for line in lines)
    assert "docker compose up -d --wait" in result.stdout
    assert "systemctl start songmaker-autodeploy.timer" in result.stdout


@pytest.mark.parametrize(
    ("env", "steps_started"),
    [
        pytest.param({"FAKE_TIMER_STATE": "active"}, [], id="timer_active"),
        pytest.param({"FAKE_TIMER_STATE": "unknown"}, [], id="timer_state_unrecognised"),
        pytest.param({"FAKE_SYSTEMCTL_BROKEN": "1"}, [], id="timer_query_fails"),
        pytest.param({"FAKE_LOCK_BUSY": "1"}, [], id="deployment_lock_held"),
        pytest.param({"FAKE_DOCKER_FAIL_ON": "volume inspect"}, [], id="volume_missing"),
        pytest.param({"FAKE_DOCKER_FAIL_ON": "pg_restore --list"}, [], id="dump_unreadable"),
        pytest.param({"FAKE_DOCKER_FAIL_ON": "config --images"}, [], id="helper_image_unknown"),
        pytest.param({"FAKE_DOCKER_FAIL_ON": "compose stop"}, DESTRUCTIVE_STEPS[:1], id="stop"),
        pytest.param(
            {"FAKE_DOCKER_FAIL_ON": "DROP DATABASE"}, DESTRUCTIVE_STEPS[:2], id="database_recreate"
        ),
        pytest.param(
            {"FAKE_DOCKER_FAIL_ON": "--single-transaction"}, DESTRUCTIVE_STEPS[:3], id="import"
        ),
        pytest.param(
            {"FAKE_DOCKER_FAIL_ON": "helper-image:pinned sh -c"},
            DESTRUCTIVE_STEPS[:4],
            id="audio_replace",
        ),
        pytest.param({"FAKE_VOLUME_FILES": "1"}, DESTRUCTIVE_STEPS[:4], id="final_count"),
    ],
)
def test_restore_fails_loudly_and_takes_no_later_step(
    docker_log: Path, snapshot: Path, env: dict[str, str], steps_started: list[str]
) -> None:
    result = _run(RESTORE_SCRIPT, docker_log, [str(snapshot)], stdin="y\n", **env)

    assert result.returncode != 0
    lines = _logged(docker_log)
    started = [step for step in DESTRUCTIVE_STEPS if any(step in line for line in lines)]
    assert started == steps_started
    assert "Restore complete" not in result.stdout
    assert "docker compose up" not in result.stdout


@pytest.mark.parametrize(
    "damage",
    ["no_manifest", "no_audio_dir", "no_dump", "audio_short_of_manifest"],
)
def test_restore_refuses_an_incomplete_snapshot_before_any_destructive_step(
    docker_log: Path, snapshot: Path, damage: str
) -> None:
    if damage == "no_manifest":
        (snapshot / "manifest.txt").unlink()
    elif damage == "no_audio_dir":
        shutil.rmtree(snapshot / "audio")
    elif damage == "no_dump":
        (snapshot / "db.dump").unlink()
    else:
        (snapshot / "audio" / "b.mp3").unlink()

    result = _run(RESTORE_SCRIPT, docker_log, [str(snapshot)], stdin="y\n")

    assert result.returncode != 0
    lines = _logged(docker_log)
    assert not any(step in line for step in DESTRUCTIVE_STEPS for line in lines)
    assert "Restore complete" not in result.stdout


def test_restore_declined_confirmation_changes_nothing(docker_log: Path, snapshot: Path) -> None:
    result = _run(RESTORE_SCRIPT, docker_log, [str(snapshot)], stdin="n\n")

    assert result.returncode == 0
    lines = _logged(docker_log)
    assert not any(step in line for step in DESTRUCTIVE_STEPS for line in lines)


def test_restore_accepts_a_relative_snapshot_path(docker_log: Path, snapshot: Path) -> None:
    result = _run(RESTORE_SCRIPT, docker_log, ["snap"], stdin="y\n")

    assert result.returncode == 0, result.stderr
    assert str(snapshot) in result.stdout


def test_audio_replacement_removes_stale_files_and_copies_dotfiles(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    (source / "covers").mkdir(parents=True)
    (source / "song.mp3").write_bytes(b"new")
    (source / "covers" / "c.jpg").write_bytes(b"cover")
    (source / ".hidden").write_bytes(b"dot")
    (destination / "old_dir").mkdir(parents=True)
    (destination / "old_dir" / "stale.mp3").write_bytes(b"stale")
    (destination / ".stale_dot").write_bytes(b"stale")

    subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; sh -c "$AUDIO_REPLACE_SCRIPT" _ "$2" "$3"',
            "bash",
            str(RESTORE_SCRIPT),
            str(source),
            str(destination),
        ],
        check=True,
    )

    restored = {
        path.relative_to(destination): path.read_bytes()
        for path in destination.rglob("*")
        if path.is_file()
    }
    expected = {
        path.relative_to(source): path.read_bytes() for path in source.rglob("*") if path.is_file()
    }
    assert restored == expected
    assert not (destination / "old_dir").exists()


def test_backup_with_zero_retention_prunes_nothing(docker_log: Path, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    old = backup_dir / "20200101_000000"
    old.mkdir(parents=True)
    os.utime(old, (1_577_836_800, 1_577_836_800))

    result = _run(BACKUP_SCRIPT, docker_log, [], BACKUP_DIR=str(backup_dir), RETENTION_DAYS="0")

    assert result.returncode == 0, result.stderr
    assert old.is_dir()
    copy_line = next(line for line in _logged(docker_log) if "cp -a" in line)
    assert "helper-image:pinned sh -c" in copy_line


def test_backup_fails_when_compose_names_no_helper_image(docker_log: Path, tmp_path: Path) -> None:
    result = _run(
        BACKUP_SCRIPT,
        docker_log,
        [],
        BACKUP_DIR=str(tmp_path / "backups"),
        FAKE_DOCKER_FAIL_ON="config --images",
    )

    assert result.returncode != 0


def test_backup_with_a_missing_volume_fails_before_any_snapshot_work(
    docker_log: Path, tmp_path: Path
) -> None:
    backup_dir = tmp_path / "backups"
    old = backup_dir / "20200101_000000"
    old.mkdir(parents=True)
    os.utime(old, (1_577_836_800, 1_577_836_800))

    result = _run(
        BACKUP_SCRIPT,
        docker_log,
        [],
        BACKUP_DIR=str(backup_dir),
        FAKE_DOCKER_FAIL_ON="volume inspect",
    )

    assert result.returncode != 0
    assert [path.name for path in backup_dir.iterdir()] == [old.name]
    lines = _logged(docker_log)
    assert not any(step in line for step in ("pg_dump", "docker run") for line in lines)
