"""Behavioral tests for scripts/restore.sh and the retention switch of scripts/backup.sh.

A fake ``docker`` executable is placed first on PATH; it records its arguments
and can be told to fail on a matching command, so no real Docker is touched.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RESTORE_SCRIPT = REPO_ROOT / "scripts" / "restore.sh"
BACKUP_SCRIPT = REPO_ROOT / "scripts" / "backup.sh"

FAKE_DOCKER = """#!/bin/bash
echo "$*" >> "$FAKE_DOCKER_LOG"
if [[ -n "${FAKE_DOCKER_FAIL_ON:-}" && "$*" == *"$FAKE_DOCKER_FAIL_ON"* ]]; then
    echo "fake docker: refused" >&2
    exit 1
fi
"""


@pytest.fixture
def docker_log(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    return tmp_path / "docker.log"


def _run(script: Path, docker_log: Path, args: list[str], *, stdin: str = "", **env: str):
    full_env = {
        **os.environ,
        "PATH": f"{docker_log.parent / 'bin'}:{os.environ['PATH']}",
        "FAKE_DOCKER_LOG": str(docker_log),
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
    (snap / "db.dump").write_bytes(b"dump")
    return snap


def _index(lines: list[str], needle: str) -> int:
    return next(i for i, line in enumerate(lines) if needle in line)


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
    recreate = _index(lines, "DROP DATABASE")
    restore = _index(lines, "pg_restore")
    audio = _index(lines, "alpine sh -c")
    assert stop < recreate < restore < audio
    assert "--exit-on-error" in lines[restore]
    assert "--single-transaction" in lines[restore]
    assert "-mindepth 1 -delete" in lines[audio]
    assert not any("compose up" in line for line in lines)
    assert "docker compose up -d --wait" in result.stdout


def test_restore_fails_loudly_and_stops_when_pg_restore_fails(
    docker_log: Path, snapshot: Path
) -> None:
    result = _run(
        RESTORE_SCRIPT, docker_log, [str(snapshot)], stdin="y\n", FAKE_DOCKER_FAIL_ON="pg_restore"
    )

    assert result.returncode != 0
    lines = _logged(docker_log)
    assert not any("alpine sh -c" in line for line in lines)
    assert "Restore complete" not in result.stdout


def test_restore_refuses_a_snapshot_without_audio_before_touching_docker(
    docker_log: Path, snapshot: Path
) -> None:
    (snapshot / "audio").rmdir()

    result = _run(RESTORE_SCRIPT, docker_log, [str(snapshot)], stdin="y\n")

    assert result.returncode != 0
    assert _logged(docker_log) == []


def test_restore_declined_confirmation_changes_nothing(docker_log: Path, snapshot: Path) -> None:
    result = _run(RESTORE_SCRIPT, docker_log, [str(snapshot)], stdin="n\n")

    assert result.returncode == 0
    assert _logged(docker_log) == []


def test_backup_with_zero_retention_prunes_nothing(docker_log: Path, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    old = backup_dir / "20200101_000000"
    old.mkdir(parents=True)
    os.utime(old, (1_577_836_800, 1_577_836_800))

    result = _run(BACKUP_SCRIPT, docker_log, [], BACKUP_DIR=str(backup_dir), RETENTION_DAYS="0")

    assert result.returncode == 0, result.stderr
    assert old.is_dir()
