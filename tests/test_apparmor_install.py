"""The AppArmor profile installer, driven as a real subprocess.

`id`, `apparmor_parser` and `aa-status` are recording fakes on PATH, built
from the same builtin-only recorder as the systemd installers' fakes; the
copy is made by the real `install`, into a temporary directory that stands
in for /etc/apparmor.d. Nothing here touches the host's AppArmor policy.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from test_install_cli_credentials_mirror import (
    INHERITED_ENVIRONMENT,
    RECORDER,
    REPO_ROOT,
    _executable,
)
from test_prove_codex_image_sandbox import proof

INSTALLER = REPO_ROOT / "scripts" / "apparmor" / "install.sh"
PROFILE = INSTALLER.parent / proof.DEFAULT_WEB_PROFILE
A_STALE_COPY = b"profile songmaker-web { # rules from an older checkout\n}\n"

# The kernel's table of loaded profiles is one file under the sandbox: a load
# writes the profile's file name there and `aa-status` lists it back. Each
# fault in FAKE_APPARMOR_FAILS breaks exactly one step of the installer.
LOADED_PROFILES = """
LOADED="$SANDBOX_ROOT/apparmor-loaded"
writable_target "$LOADED" || refuse "loaded-profile table is a symlink"
"""

FAKE_ID = '#!/bin/bash\nFAKE_NAME=id\n' + RECORDER + """
[ "$*" = "-u" ] || refuse "an id query other than -u"
printf '%s\\n' "${FAKE_UID:-0}"
"""

FAKE_APPARMOR_PARSER = (
    '#!/bin/bash\nFAKE_NAME=apparmor_parser\n' + RECORDER + LOADED_PROFILES + """
record "apparmor_parser $*"
[ $# -eq 2 ] || refuse "an argument count the installer never uses"
case "$1" in
    -QK)
        [ "${FAKE_APPARMOR_FAILS:-}" != validate ]
        exit $? ;;
    -r)
        [ "${FAKE_APPARMOR_FAILS:-}" != load ] || exit 1
        if [ "${FAKE_APPARMOR_FAILS:-}" != report ]; then
            printf '%s\\n' "${2##*/}" > "$LOADED"
        fi
        exit 0 ;;
esac
refuse "option '$1' — this fake models -QK and -r only"
"""
)

FAKE_AA_STATUS = (
    '#!/bin/bash\nFAKE_NAME=aa-status\n' + RECORDER + LOADED_PROFILES + """
record "aa-status $*"
case "$*" in
    --enabled)
        [ "${FAKE_APPARMOR_FAILS:-}" != enabled ]
        exit $? ;;
    "")
        if [ -f "$LOADED" ]; then
            while IFS= read -r profile; do
                printf '   %s\\n' "$profile"
            done < "$LOADED"
        fi
        exit 0 ;;
esac
refuse "'$*' — this fake models --enabled and the profile listing only"
"""
)


@pytest.fixture
def run_installer(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(fake_bin / "id", FAKE_ID)
    _executable(fake_bin / "apparmor_parser", FAKE_APPARMOR_PARSER)
    _executable(fake_bin / "aa-status", FAKE_AA_STATUS)
    recording = tmp_path / "recording"
    recording.write_text("")
    installed_dir = tmp_path / "apparmor.d"
    installed_dir.mkdir()

    def _run(
        *arguments: str,
        uid: str = "0",
        fault: str = "",
        apparmor_dir: Path = installed_dir,
    ) -> subprocess.CompletedProcess[str]:
        environment = {
            name: os.environ[name]
            for name in INHERITED_ENVIRONMENT
            if name in os.environ
        }
        environment.update(
            {
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "SANDBOX_ROOT": str(tmp_path),
                "RECORDING": str(recording),
                "SONGMAKER_APPARMOR_DIR": str(apparmor_dir),
                "FAKE_UID": uid,
                "FAKE_APPARMOR_FAILS": fault,
            },
        )
        return subprocess.run(
            [str(INSTALLER), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    _run.recording = recording
    _run.installed_dir = installed_dir
    _run.loaded = tmp_path / "apparmor-loaded"
    return _run


def _directory_contents(directory: Path) -> dict[str, bytes]:
    return {entry.name: entry.read_bytes() for entry in directory.iterdir()}


@pytest.mark.parametrize("existing_copy", [None, A_STALE_COPY], ids=["fresh", "stale"])
def test_installs_a_byte_identical_world_readable_copy_and_loads_that_copy(
    run_installer, existing_copy: bytes | None,
) -> None:
    installed = run_installer.installed_dir / proof.DEFAULT_WEB_PROFILE
    if existing_copy is not None:
        installed.write_bytes(existing_copy)
        installed.chmod(0o600)

    result = run_installer()

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert installed.read_bytes() == PROFILE.read_bytes()
    assert stat.S_IMODE(installed.stat().st_mode) == 0o644
    assert run_installer.recording.read_text().splitlines() == [
        "aa-status --enabled",
        f"apparmor_parser -QK {PROFILE}",
        f"apparmor_parser -r {installed}",
        "aa-status ",
    ]
    assert run_installer.loaded.read_text() == f"{proof.DEFAULT_WEB_PROFILE}\n"
    assert f"as {installed} and loaded it; it loads again at every boot" in result.stdout


def test_a_second_run_leaves_the_same_installed_and_loaded_profile(run_installer) -> None:
    first = run_installer()
    installed_after_first = _directory_contents(run_installer.installed_dir)
    loaded_after_first = run_installer.loaded.read_text()

    second = run_installer()

    assert (first.returncode, second.returncode) == (0, 0)
    assert _directory_contents(run_installer.installed_dir) == installed_after_first
    assert run_installer.loaded.read_text() == loaded_after_first
    assert second.stdout == first.stdout


@pytest.mark.parametrize(
    "fault, message",
    [
        ("enabled", "AppArmor is not enabled; refusing to load the profile."),
        ("validate", "The songmaker-web profile does not parse; nothing was installed."),
        ("load", "but the kernel did not load it."),
        ("report", "AppArmor did not report the songmaker-web profile after loading it."),
    ],
)
def test_each_failing_step_fails_loud_with_its_own_message(
    run_installer, fault: str, message: str,
) -> None:
    result = run_installer(fault=fault)

    assert result.returncode == 1
    assert message in result.stderr
    assert "Installed AppArmor profile" not in result.stdout


def test_a_copy_that_cannot_be_written_fails_loud_before_any_load(
    run_installer, tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "no-apparmor.d"

    result = run_installer(apparmor_dir=missing_dir)

    assert result.returncode == 1
    assert (
        f"Could not install the songmaker-web profile as {missing_dir}/songmaker-web."
        in result.stderr
    )
    assert "apparmor_parser -r" not in run_installer.recording.read_text()


def test_a_profile_that_does_not_parse_leaves_the_installed_copy_untouched(
    run_installer,
) -> None:
    (run_installer.installed_dir / proof.DEFAULT_WEB_PROFILE).write_bytes(A_STALE_COPY)
    before = _directory_contents(run_installer.installed_dir)

    result = run_installer(fault="validate")

    assert result.returncode == 1
    assert _directory_contents(run_installer.installed_dir) == before
    assert "apparmor_parser -r" not in run_installer.recording.read_text()


def test_the_installer_refuses_to_run_without_root(run_installer) -> None:
    result = run_installer(uid="1000")

    assert result.returncode == 1
    assert "Run this script as root" in result.stderr
    assert not run_installer.recording.read_text()
    assert not any(run_installer.installed_dir.iterdir())


@pytest.mark.parametrize("name", ["no-such-profile", "../songmaker-web", "install.sh"])
def test_the_installer_refuses_a_name_that_is_not_a_profile_beside_it(
    run_installer, name: str,
) -> None:
    """The argument names a profile in this directory, never a path or the script."""
    result = run_installer(name)

    assert result.returncode == 1
    assert f"{name} is not the name of a profile file" in result.stderr
    assert not run_installer.recording.read_text()
    assert not any(run_installer.installed_dir.iterdir())
