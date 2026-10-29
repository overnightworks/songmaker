"""The AppArmor profile installer, driven as a real subprocess.

The installer and its profile are copied into a temporary script directory,
so a test can put a symlink beside them or edit the source mid-run. `id`,
`apparmor_parser` and `aa-status` are recording fakes on PATH, built from the
same builtin-only recorder as the systemd installers' fakes; the copy is made
by the real `mktemp`, `cp` and `mv`, into a temporary directory that stands in
for /etc/apparmor.d. Nothing here touches the host's AppArmor policy.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from support.codex_sandbox_proof import proof
from support.install_script_fakes import (
    INHERITED_ENVIRONMENT,
    RECORDER,
    make_executable,
)
from support.repository_root import REPOSITORY_ROOT

INSTALLER = REPOSITORY_ROOT / "scripts" / "apparmor" / "install_profile.sh"
PROFILE = INSTALLER.parent / proof.DEFAULT_WEB_PROFILE
A_STALE_COPY = b"profile songmaker-web { # rules from an older checkout\n}\n"
A_LONG_AGO_NS = 1_600_000_000 * 10**9

# The kernel's table of loaded profiles is a directory under the sandbox: a
# load stores the file's bytes under every profile name the file declares,
# `apparmor_parser -N` reports those names, and `aa-status` lists the loaded
# names back. Each fault in FAKE_APPARMOR_FAILS breaks exactly one step of the
# installer; a load fault strikes the first load only, so the installer's
# reload of the previous copy goes through.
KERNEL_TABLE = """
KERNEL="$SANDBOX_ROOT/apparmor-kernel"
FAULT_SPENT="$SANDBOX_ROOT/apparmor-fault-spent"

copy_lines() {
    writable_target "$2" || refuse "a copy outside the sandbox or through a symlink"
    local line
    while IFS= read -r line || [ -n "$line" ]; do
        printf '%s\\n' "$line"
    done < "$1" > "$2"
}

declared_profiles() {
    local line pattern='^[[:space:]]*profile[[:space:]]+"?([^"[:space:]]+)'
    while IFS= read -r line || [ -n "$line" ]; do
        if [[ $line =~ $pattern ]]; then
            printf '%s\\n' "${BASH_REMATCH[1]}"
        fi
    done < "$1"
}

first_load_fault() {
    [ "${FAKE_APPARMOR_FAILS:-}" = "$1" ] && [ ! -e "$FAULT_SPENT" ] || return 1
    writable_target "$FAULT_SPENT" || refuse "fault marker is a symlink"
    : > "$FAULT_SPENT"
}
"""

FAKE_ID = '#!/bin/bash\nFAKE_NAME=id\n' + RECORDER + """
[ "$*" = "-u" ] || refuse "an id query other than -u"
printf '%s\\n' "${FAKE_UID:-0}"
"""

FAKE_APPARMOR_PARSER = (
    '#!/bin/bash\nFAKE_NAME=apparmor_parser\n' + RECORDER + KERNEL_TABLE + """
record "apparmor_parser $*"
if [ $# -eq 3 ] && [ "$1 $2" = "-QK -N" ]; then
    declared_profiles "$3"
    exit 0
fi
[ $# -eq 2 ] || refuse "an argument count the installer never uses"
case "$1" in
    -QK)
        copy_lines "$2" "$SANDBOX_ROOT/apparmor-validated"
        if [ "${FAKE_APPARMOR_FAILS:-}" = source-changes ]; then
            writable_target "$FAKE_SOURCE_PROFILE" || refuse "a source outside the sandbox"
            printf 'profile songmaker-web { # edited while the installer ran\\n}\\n' \\
                > "$FAKE_SOURCE_PROFILE"
        fi
        [ "${FAKE_APPARMOR_FAILS:-}" != validate ]
        exit $? ;;
    -r)
        first_load_fault load && exit 1
        names="$(declared_profiles "$2")"
        [ -n "$names" ] || refuse "a file that declares no profile"
        first_load_fault report && exit 0
        while IFS= read -r name; do
            copy_lines "$2" "$KERNEL/$name"
        done <<< "$names"
        exit 0 ;;
esac
refuse "option '$1' — this fake models -QK, -QK -N and -r only"
"""
)

FAKE_AA_STATUS = (
    '#!/bin/bash\nFAKE_NAME=aa-status\n' + RECORDER + KERNEL_TABLE + """
record "aa-status $*"
case "$*" in
    --enabled)
        [ "${FAKE_APPARMOR_FAILS:-}" != enabled ]
        exit $? ;;
    "")
        for loaded in "$KERNEL"/*; do
            [ -e "$loaded" ] && printf '   %s\\n' "${loaded##*/}"
        done
        exit 0 ;;
esac
refuse "'$*' — this fake models --enabled and the profile listing only"
"""
)


@pytest.fixture
def run_installer(tmp_path: Path):
    script_dir = tmp_path / "apparmor"
    script_dir.mkdir()
    installer = script_dir / INSTALLER.name
    shutil.copy(INSTALLER, installer)
    source = script_dir / proof.DEFAULT_WEB_PROFILE
    source.write_bytes(PROFILE.read_bytes())
    os.utime(source, ns=(A_LONG_AGO_NS, A_LONG_AGO_NS))
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "id", FAKE_ID)
    make_executable(fake_bin / "apparmor_parser", FAKE_APPARMOR_PARSER)
    make_executable(fake_bin / "aa-status", FAKE_AA_STATUS)
    recording = tmp_path / "recording"
    recording.write_text("")
    installed_dir = tmp_path / "apparmor.d"
    installed_dir.mkdir()
    kernel = tmp_path / "apparmor-kernel"
    kernel.mkdir()

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
                "FAKE_SOURCE_PROFILE": str(source),
            },
        )
        return subprocess.run(
            [str(installer), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    _run.recording = recording
    _run.script_dir = script_dir
    _run.source = source
    _run.installed_dir = installed_dir
    _run.kernel = kernel
    _run.validated = tmp_path / "apparmor-validated"
    return _run


def _directory_contents(directory: Path) -> dict[str, bytes]:
    return {entry.name: entry.read_bytes() for entry in directory.iterdir()}


@pytest.mark.parametrize("existing_copy", [None, A_STALE_COPY], ids=["fresh", "stale"])
def test_installs_a_byte_identical_world_readable_fresh_copy_and_loads_that_copy(
    run_installer, existing_copy: bytes | None,
) -> None:
    installed = run_installer.installed_dir / proof.DEFAULT_WEB_PROFILE
    if existing_copy is not None:
        installed.write_bytes(existing_copy)
        installed.chmod(0o600)

    result = run_installer()

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert _directory_contents(run_installer.installed_dir) == {
        proof.DEFAULT_WEB_PROFILE: PROFILE.read_bytes(),
    }
    assert stat.S_IMODE(installed.stat().st_mode) == 0o644
    assert installed.stat().st_mtime_ns > run_installer.source.stat().st_mtime_ns
    enabled, validate, names, load, listing = run_installer.recording.read_text().splitlines()
    assert (enabled, load, listing) == (
        "aa-status --enabled", f"apparmor_parser -r {installed}", "aa-status ",
    )
    assert validate.startswith(
        f"apparmor_parser -QK {run_installer.installed_dir}/.{proof.DEFAULT_WEB_PROFILE}.",
    )
    assert names == validate.replace("-QK", "-QK -N", 1)
    assert _directory_contents(run_installer.kernel) == {
        proof.DEFAULT_WEB_PROFILE: PROFILE.read_bytes(),
    }
    assert f"as {installed} and loaded it; it loads again at every boot" in result.stdout


def test_a_second_run_leaves_the_same_installed_and_loaded_profile(run_installer) -> None:
    first = run_installer()
    installed_after_first = _directory_contents(run_installer.installed_dir)
    loaded_after_first = _directory_contents(run_installer.kernel)

    second = run_installer()

    assert (first.returncode, second.returncode) == (0, 0)
    assert _directory_contents(run_installer.installed_dir) == installed_after_first
    assert _directory_contents(run_installer.kernel) == loaded_after_first
    assert second.stdout == first.stdout


def test_the_bytes_validated_are_the_bytes_installed_even_if_the_source_changes(
    run_installer,
) -> None:
    result = run_installer(fault="source-changes")

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert run_installer.source.read_bytes() != PROFILE.read_bytes()
    installed = run_installer.installed_dir / proof.DEFAULT_WEB_PROFILE
    assert installed.read_bytes() == run_installer.validated.read_bytes() == PROFILE.read_bytes()


@pytest.mark.parametrize("existing_copy", [None, A_STALE_COPY], ids=["first-install", "update"])
@pytest.mark.parametrize(
    "fault, message, reloads_the_previous_copy",
    [
        ("enabled", "AppArmor is not enabled; refusing to load the profile.", False),
        ("validate", "The songmaker-web profile does not parse; nothing was installed.", False),
        ("load", "The kernel did not load", True),
        ("report", "AppArmor did not report the songmaker-web profile after loading it.", True),
    ],
)
def test_each_failing_step_fails_loud_and_leaves_the_previous_copy_installed_and_loaded(
    run_installer,
    fault: str,
    message: str,
    reloads_the_previous_copy: bool,
    existing_copy: bytes | None,
) -> None:
    """A failure leaves the target directory as it was, without a staged dotfile."""
    installed = run_installer.installed_dir / proof.DEFAULT_WEB_PROFILE
    if existing_copy is not None:
        installed.write_bytes(existing_copy)
        installed.chmod(0o640)
    before = _directory_contents(run_installer.installed_dir)

    result = run_installer(fault=fault)

    assert result.returncode == 1
    assert message in result.stderr
    assert "Installed AppArmor profile" not in result.stdout
    assert _directory_contents(run_installer.installed_dir) == before
    expected_kernel = (
        {proof.DEFAULT_WEB_PROFILE: existing_copy}
        if reloads_the_previous_copy and existing_copy is not None
        else {}
    )
    assert _directory_contents(run_installer.kernel) == expected_kernel
    if existing_copy is not None:
        assert stat.S_IMODE(installed.stat().st_mode) == 0o640


@pytest.mark.parametrize("already_installed", [False, True], ids=["first-install", "update"])
@pytest.mark.parametrize(
    "declared",
    [
        "profile songmaker-web-staging {\n}\n",
        "profile old-songmaker-web {\n}\n",
        "profile songmaker-web {\n}\nprofile songmaker-web-helper {\n}\n",
    ],
    ids=["another-name", "a-name-containing-it", "an-extra-profile"],
)
def test_a_file_declaring_anything_but_the_requested_profile_is_refused_before_replacement(
    run_installer, declared: str, already_installed: bool,
) -> None:
    """An older requested profile still loaded would answer aa-status for it."""
    run_installer.source.write_text(declared)
    if already_installed:
        for directory in (run_installer.installed_dir, run_installer.kernel):
            (directory / proof.DEFAULT_WEB_PROFILE).write_bytes(A_STALE_COPY)
    installed_before = _directory_contents(run_installer.installed_dir)
    loaded_before = _directory_contents(run_installer.kernel)

    result = run_installer()

    assert result.returncode == 1
    assert "must declare the songmaker-web profile and nothing else" in result.stderr
    assert _directory_contents(run_installer.installed_dir) == installed_before
    assert _directory_contents(run_installer.kernel) == loaded_before


def test_a_directory_that_cannot_be_written_fails_loud_before_any_load(
    run_installer, tmp_path: Path,
) -> None:
    missing_dir = tmp_path / "no-apparmor.d"

    result = run_installer(apparmor_dir=missing_dir)

    assert result.returncode == 1
    assert f"Could not stage the songmaker-web profile in {missing_dir}." in result.stderr
    assert "apparmor_parser" not in run_installer.recording.read_text()


def test_the_installer_refuses_to_run_without_root(run_installer) -> None:
    result = run_installer(uid="1000")

    assert result.returncode == 1
    assert "Run this script as root" in result.stderr
    assert not run_installer.recording.read_text()
    assert not any(run_installer.installed_dir.iterdir())


def _refuses_the_name(run_installer, name: str) -> None:
    result = run_installer(name)

    assert result.returncode == 1
    assert f"{name} is not the name of a profile file" in result.stderr
    assert not run_installer.recording.read_text()
    assert not any(run_installer.installed_dir.iterdir())


@pytest.mark.parametrize("name", ["no-such-profile", "../songmaker-web", "install_profile.sh"])
def test_the_installer_refuses_a_name_that_is_not_a_profile_beside_it(
    run_installer, name: str,
) -> None:
    """The argument names a profile in this directory, never a path or the script."""
    _refuses_the_name(run_installer, name)


@pytest.mark.parametrize("points_outside", [True, False], ids=["outside", "sibling"])
def test_the_installer_refuses_a_name_that_is_a_symlink_beside_it(
    run_installer, tmp_path: Path, points_outside: bool,
) -> None:
    """A link beside the script could carry any host file into the policy."""
    target = run_installer.source
    if points_outside:
        target = tmp_path / "elsewhere"
        target.write_bytes(PROFILE.read_bytes())
    (run_installer.script_dir / "linked-profile").symlink_to(target)

    _refuses_the_name(run_installer, "linked-profile")
