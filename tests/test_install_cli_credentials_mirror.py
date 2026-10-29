"""The mirror installer, driven as a real subprocess.

Two crashes shipped in this script because nothing ever ran it: `bash -n`
sees neither an unset variable at runtime nor a missing parent directory.
So this drives the real file, from a throwaway checkout, with `sudo`,
`systemctl` and `getent` replaced by fakes on PATH — no real units, no root,
nothing outside the temporary directories.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.install_script_fakes import (
    DEFAULT_SUDO_USER,
    FAKE_GETENT,
    FAKE_SUDO,
    FAKE_SYSTEMCTL,
    INHERITED_ENVIRONMENT,
    linked_worktree_of,
    make_executable,
)
from support.repository_root import REPOSITORY_ROOT

INSTALLER = REPOSITORY_ROOT / "scripts" / "install-cli-credentials-mirror.sh"

COPIED_SCRIPTS = (
    "install-cli-credentials-mirror.sh",
    "mirror_agent_cli_credentials.py",
    "dotenv_file.py",
    "main_checkout.py",
    "check_agent_cli_mounts.sh",
    "agent_cli_paths.sh",
    "alert.sh",
    "songmaker-cli-credentials-mirror.service",
    "songmaker-cli-credentials-mirror.path",
    "songmaker-cli-credentials-mirror.timer",
    "songmaker-alert@.service",
)

@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A git checkout that is its own main worktree, with the scripts in it."""
    root = tmp_path / "songmaker"
    (root / "scripts").mkdir(parents=True)
    for name in COPIED_SCRIPTS:
        source = REPOSITORY_ROOT / "scripts" / name
        target = root / "scripts" / name
        target.write_bytes(source.read_bytes())
        target.chmod(source.stat().st_mode)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A signed-in operator whose ~/.songmaker does not exist yet.

    That absence is the point: the mirror has to create the whole path, not
    just its last segment.
    """
    signed_in = tmp_path / "home"
    for relative, document in (
        (
            ".claude/.credentials.json",
            '{"claudeAiOauth": {"accessToken": "a", "expiresAt": 1, '
            '"scopes": ["user:inference"], "refreshToken": "secret"}}',
        ),
        (
            ".grok/auth.json",
            '{"realm": {"key": "k", "auth_mode": "oidc", "create_time": "t", "expires_at": "t", '
            '"user_id": "u", "team_id": "t", "principal_type": "User", "principal_id": "p", '
            '"oidc_issuer": "i", "oidc_client_id": "c", "coding_data_retention_opt_out": true, '
            '"coding_data_team": true, "team_zero_data_retention": true, '
            '"refresh_token": "secret"}}',
        ),
        (
            ".codex/auth.json",
            '{"auth_mode": "chatgpt", "OPENAI_API_KEY": null, '
            '"last_refresh": "t", "tokens": {"id_token": "i", '
            '"access_token": "a", "account_id": "n", "refresh_token": "secret"}}',
        ),
    ):
        path = signed_in / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document)
    return signed_in


@pytest.fixture
def run_installer(tmp_path: Path, checkout: Path, home: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    make_executable(fake_bin / "sudo", FAKE_SUDO)
    make_executable(fake_bin / "systemctl", FAKE_SYSTEMCTL)
    make_executable(fake_bin / "getent", FAKE_GETENT)
    units = tmp_path / "systemd"
    units.mkdir()
    recording = tmp_path / "recording"
    recording.write_text("")
    state = tmp_path / "systemctl-state"
    state.write_text("")
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    codex_resources = tmp_path / "codex-resources"
    codex_resources.mkdir()
    (codex_resources / "bwrap").symlink_to("/bin/sh")

    def _environment(**overrides: str) -> dict[str, str]:
        built = {name: os.environ[name] for name in INHERITED_ENVIRONMENT
                 if name in os.environ}
        built.update(overrides)
        built.update({
            # Last word, always: these are the containment itself.
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "TMPDIR": str(scratch),
            "HOME": str(home),
            "SANDBOX_ROOT": str(tmp_path),
            "RECORDING": str(recording),
            "FAKE_OPERATOR_HOME": str(home),
            "SONGMAKER_CLAUDE_CLI": "/bin/sh",
            "SONGMAKER_GROK_CLI": "/bin/sh",
            "SONGMAKER_CODEX_CLI": "/bin/sh",
            "SONGMAKER_CODEX_CODE_MODE_HOST": "/bin/sh",
            "SONGMAKER_CODEX_RESOURCES": str(codex_resources),
        })
        built.setdefault("SUDO_USER", DEFAULT_SUDO_USER)
        built.setdefault("SONGMAKER_UNIT_DIR", str(units))
        if "SONGMAKER_UNIT_DIR" in overrides:
            built["SONGMAKER_UNIT_DIR"] = overrides["SONGMAKER_UNIT_DIR"]
        return built

    def _seed_mirror() -> None:
        """What systemd would do when the installer asks it to start the unit.

        The fakes do not run anything, so the effect of `systemctl start` on
        the mirror service is produced here instead — by the real mirror
        script, in the same sandbox, which is what systemd would have run.
        Without it the installer's own closing preflight would fail on files
        that nobody wrote. That the script really creates its directories, and
        with which mode, is pinned against the script itself in
        tests/scripts/test_mirror_agent_cli_credentials.py — not through a fake.
        """
        subprocess.run(
            [
                str(checkout / "scripts" / "mirror_agent_cli_credentials.py"),
                "--home", str(home),
                "--mirror-dir", str(home / ".songmaker/agent-cli-credentials"),
            ],
            env=_environment(), text=True, capture_output=True, check=True,
        )

    def _run(
        *arguments: str,
        from_checkout: Path | None = None,
        seed_mirror: bool = True,
        **overrides: str,
    ) -> subprocess.CompletedProcess[str]:
        """Run the installer. Every invocation goes through here, always.

        There is deliberately no second way to start it: a test that built its
        own environment would be one PATH away from the real sudo and the real
        /etc/systemd/system the moment an early guard regressed.
        """
        started_from = from_checkout or checkout
        if seed_mirror:
            _seed_mirror()
        return subprocess.run(
            [str(started_from / "scripts" / INSTALLER.name), *arguments],
            cwd=started_from,
            env=_environment(**overrides),
            text=True,
            capture_output=True,
            check=False,
        )

    _run.units = units
    _run.home = home
    _run.checkout = checkout
    _run.sandbox = tmp_path
    _run.recording = recording
    _run.state = state
    _run.environment = _environment
    return _run


def _recorded(run_installer) -> list[str]:
    return run_installer.recording.read_text().splitlines()


def test_the_installer_runs_through(run_installer) -> None:
    """The whole thing, end to end. Both shipped crashes died here."""
    result = run_installer()

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_it_writes_the_four_units_it_promises(run_installer) -> None:
    run_installer()

    installed = {path.name for path in run_installer.units.iterdir()}
    assert installed == {
        "songmaker-cli-credentials-mirror.service",
        "songmaker-cli-credentials-mirror.path",
        "songmaker-cli-credentials-mirror.timer",
        "songmaker-alert@.service",
    }


def test_the_unit_it_writes_names_this_checkout_and_this_home(
    run_installer, checkout: Path, home: Path,
) -> None:
    run_installer()

    unit = (run_installer.units / "songmaker-cli-credentials-mirror.service").read_text()
    exec_start = next(
        line for line in unit.splitlines() if line.startswith("ExecStart=")
    )
    assert str(checkout / "scripts" / "mirror_agent_cli_credentials.py") in exec_start
    assert f"--home {home}" in exec_start
    assert f"--mirror-dir {home}/.songmaker/agent-cli-credentials" in exec_start


def test_it_checks_the_mounts_as_the_operator_it_installed_for(
    run_installer, checkout: Path, home: Path,
) -> None:
    """Not as root under sudo: root sees a different home and a different mirror."""
    run_installer()

    preflight = checkout / "scripts" / "check_agent_cli_mounts.sh"
    assert (
        f"sudo -u {DEFAULT_SUDO_USER} {preflight} --home {home} "
        f"--mirror-dir {home}/.songmaker/agent-cli-credentials"
    ) in _recorded(run_installer)


def test_the_seeded_mirror_holds_one_file_per_cli(
    run_installer, home: Path,
) -> None:
    """The seam the closing preflight then judges, stated as what it is.

    `_seed_mirror()` runs the real mirror script before the installer starts,
    standing in for the `systemctl start` the fakes do not run. So what this
    pins is that seam — a file per CLI, in the two-level path the script had to
    create — and not the installer, which writes none of them.
    """
    run_installer()

    mirrored = home / ".songmaker/agent-cli-credentials"
    assert {path.name for path in mirrored.iterdir()} >= {
        "claude.json", "grok.json", "codex.json",
    }


def test_no_renewal_secret_is_in_anything_it_published(
    run_installer, home: Path,
) -> None:
    run_installer()

    published = "\n".join(
        path.read_text()
        for path in (home / ".songmaker/agent-cli-credentials").glob("*.json")
    )
    assert "secret" not in published


def test_it_asks_systemd_for_each_unit_in_the_right_order(run_installer) -> None:
    """Read from the recording: the fakes do nothing else worth asserting."""
    run_installer()

    asked = [line for line in _recorded(run_installer) if "systemctl" in line]
    assert any("daemon-reload" in line for line in asked)
    for expected in (
        "enable songmaker-cli-credentials-mirror.service",
        "enable --now songmaker-cli-credentials-mirror.path",
        "enable --now songmaker-cli-credentials-mirror.timer",
        "start songmaker-cli-credentials-mirror.service",
    ):
        assert any(line.endswith(expected) for line in asked), f"{expected}\n{asked}"
    reloaded = next(i for i, line in enumerate(asked) if "daemon-reload" in line)
    started = next(
        i for i, line in enumerate(asked)
        if line.endswith("start songmaker-cli-credentials-mirror.service")
    )
    assert reloaded < started, "units must be on disk and reloaded before a start"


def test_nothing_it_asked_for_named_a_target_outside_the_sandbox(
    run_installer,
) -> None:
    """The whole containment claim, as one assertion over what was recorded."""
    run_installer()

    for line in _recorded(run_installer):
        for word in line.split():
            if word.startswith("/"):
                assert str(run_installer.sandbox) in word or word == "/bin/sh", (
                    f"{word} is outside the sandbox\n{line}"
                )


def test_it_refuses_a_linked_worktree(run_installer, tmp_path) -> None:
    """These units outlive the shell; a throwaway checkout must not own them."""
    linked = linked_worktree_of(run_installer.checkout, tmp_path)

    result = run_installer(from_checkout=linked)

    assert result.returncode == 1
    assert "linked worktree" in result.stderr


def test_a_regressed_guard_reaches_a_fake_that_does_nothing(run_installer) -> None:
    """The net under the guards, stated as what it is now.

    Pointed at the real unit directory, the run must die on the fake — and
    because the fakes execute nothing, "die on the fake" is provable: the call
    is in the recording, and /etc/systemd/system is untouched.
    """
    before = sorted(Path("/etc/systemd/system").glob("songmaker-cli-credentials-*"))

    result = run_installer("--force", SONGMAKER_UNIT_DIR="/etc/systemd/system")

    assert result.returncode == 97, f"{result.stdout}{result.stderr}"
    assert "outside the sandbox" in result.stderr
    assert any("/etc/systemd/system" in line for line in _recorded(run_installer))
    assert sorted(Path("/etc/systemd/system").glob("songmaker-cli-credentials-*")) == before


@pytest.mark.parametrize(
    ("program", "argv"),
    [
        ("sudo", ["install", "-m", "0644", "{source}", "/etc/systemd/system/x"]),
        ("sudo", ["install", "-m", "0644", "{source}", "{sandbox}/../escape"]),
        ("sudo", ["-u", "somebody", "/usr/bin/id"]),
        ("sudo", ["id"]),
        ("sudo", ["install", "-m", "0644", "{source}"]),
        ("sudo", ["install", "-t", "/etc/systemd/system", "{source}"]),
        ("systemctl", ["mask", "songmaker-cli-credentials-mirror.service"]),
        ("systemctl", ["start", "../../../evil.service"]),
    ],
)
def test_a_fake_refuses_and_does_nothing(run_installer, tmp_path, program, argv) -> None:
    """Refusal is rc 97, and nothing happened — there is nothing that could."""
    source = tmp_path / "unit-to-install"
    source.write_text("[Service]\n")
    filled = [a.format(source=source, sandbox=run_installer.sandbox) for a in argv]

    result = subprocess.run(
        [program, *filled], env=run_installer.environment(),
        text=True, capture_output=True, check=False, cwd=run_installer.sandbox,
    )

    assert result.returncode == 97, f"{result.stdout}{result.stderr}"
    assert f"fake {program}: refusing" in result.stderr
    assert not Path("/etc/systemd/system/x").exists()
    assert not (run_installer.sandbox.parent / "escape").exists()


def test_a_fake_refuses_a_write_that_would_travel_through_a_symlink(
    run_installer, tmp_path: Path,
) -> None:
    """A textual prefix says yes to a link; the redirect behind it lands outside."""
    outside = tmp_path.parent / "outside-the-sandbox"
    outside.write_text("untouched")
    target = run_installer.sandbox / "looks-like-it-is-inside"
    target.symlink_to(outside)
    source = run_installer.sandbox / "unit-to-install"
    source.write_text("[Service]\n")

    result = subprocess.run(
        ["sudo", "install", "-m", "0644", str(source), str(target)],
        env=run_installer.environment(),
        text=True, capture_output=True, check=False, cwd=run_installer.sandbox,
    )

    assert result.returncode == 97, f"{result.stdout}{result.stderr}"
    assert "through a symlink" in result.stderr
    assert outside.read_text() == "untouched"


def test_a_fake_records_even_what_it_refuses(run_installer) -> None:
    """A refusal that left no trace would be a fake that hid what was asked."""
    subprocess.run(
        ["sudo", "id"], env=run_installer.environment(),
        text=True, capture_output=True, check=False,
    )

    assert any(line == "sudo id" for line in _recorded(run_installer))



# Every unit the installer writes, and every way a stranger used to slip past.
FOREIGN_UNITS = {
    "service-another-checkout": (
        "songmaker-cli-credentials-mirror.service",
        "[Service]\nExecStart=/somewhere/else/mirror_agent_cli_credentials.py\n",
    ),
    # An unbounded prefix let this through: it starts with our script's path.
    "service-lookalike-suffix": (
        "songmaker-cli-credentials-mirror.service",
        "[Service]\nExecStart={mirror_script}.evil\n",
    ),
    # No directive at all: a file we cannot identify is the one to stop at.
    "service-unidentifiable": (
        "songmaker-cli-credentials-mirror.service",
        "[Service]\nType=oneshot\n",
    ),
    "path-another-home": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged=/home/someone-else/.claude/.credentials.json\n",
    ),
    # Same operator, different checkout: "somewhere under this home" is not
    # ownership, which is why the path unit is matched exactly.
    "path-same-home-other-file": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.grok/auth.json\n",
    ),
    "timer-drives-another-service": (
        "songmaker-cli-credentials-mirror.timer",
        "[Timer]\nUnit=somebody-elses.service\n",
    ),
    # Unit= holds one value; anything after it is not ours. Treating it like a
    # command line, where a space starts the arguments, let this through.
    "timer-with-trailing-junk": (
        "songmaker-cli-credentials-mirror.timer",
        "[Timer]\nUnit=songmaker-cli-credentials-mirror.service other\n",
    ),
    "path-with-trailing-junk": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.claude/.credentials.json other\n",
    ),
    # The first watch is ours, the ones after it are not. Reading only the
    # first PathChanged= line left these invisible.
    # Three right lines and a fourth foreign one: proving the expected watches
    # are present says nothing about what else the unit watches.
    "path-extra-foreign-watch": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.claude/.credentials.json\n"
        "PathChanged={home}/.grok/auth.json\n"
        "PathChanged={home}/.codex/auth.json\n"
        "PathChanged=/home/someone-else/.claude/.credentials.json\n",
    ),
    # Same, through the other directive the unit legitimately uses.
    "path-extra-foreign-modified-watch": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.claude/.credentials.json\n"
        "PathChanged={home}/.grok/auth.json\n"
        "PathChanged={home}/.codex/auth.json\n"
        "PathModified=/home/someone-else/.grok/auth.json\n",
    ),
    "path-foreign-watch-on-a-later-line": (
        "songmaker-cli-credentials-mirror.path",
        "[Path]\nPathChanged={home}/.claude/.credentials.json\n"
        "PathChanged=/home/someone-else/.grok/auth.json\n",
    ),
    "alert-another-checkout": (
        "songmaker-alert@.service",
        "[Service]\nExecStart=/somewhere/else/scripts/alert.sh \"subject\"\n",
    ),
}


@pytest.mark.parametrize("case", sorted(FOREIGN_UNITS))
def test_it_refuses_any_unit_that_belongs_to_something_else(
    run_installer, case,
) -> None:
    run_installer()
    name, body = FOREIGN_UNITS[case]
    unit = run_installer.units / name
    unit.write_text(
        body.format(
            mirror_script=run_installer.checkout
            / "scripts" / "mirror_agent_cli_credentials.py",
            home=run_installer.home,
        ),
    )

    result = run_installer()

    assert result.returncode == 1, f"stdout:\n{result.stdout}"
    assert "belongs to something else" in result.stderr


@pytest.mark.parametrize("case", sorted(FOREIGN_UNITS))
def test_force_takes_any_of_them_over(run_installer, case) -> None:
    run_installer()
    name, body = FOREIGN_UNITS[case]
    unit = run_installer.units / name
    unit.write_text(
        body.format(
            mirror_script=run_installer.checkout
            / "scripts" / "mirror_agent_cli_credentials.py",
            home=run_installer.home,
        ),
    )

    result = run_installer("--force")

    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    assert "somewhere else" not in unit.read_text()


def test_our_own_unit_with_changed_arguments_is_still_ours(run_installer) -> None:
    """A guard that fired on every upgrade would be switched off within a week."""
    run_installer()
    unit = run_installer.units / "songmaker-cli-credentials-mirror.service"
    unit.write_text(unit.read_text().replace("--mirror-dir", "--verbose --mirror-dir"))

    result = run_installer()

    assert result.returncode == 0, f"stderr:\n{result.stderr}"


def test_a_refused_takeover_replaces_nothing_at_all(run_installer) -> None:
    """Every check before the first write: no half-installed machine."""
    run_installer()
    alert = run_installer.units / "songmaker-alert@.service"
    alert.write_text("[Service]\nExecStart=/untouched\n")
    unit = run_installer.units / "songmaker-cli-credentials-mirror.service"
    unit.write_text(
        unit.read_text().replace("ExecStart=", "ExecStart=/somewhere/else/", 1),
    )

    run_installer()

    assert alert.read_text() == "[Service]\nExecStart=/untouched\n"


# The preflight the installer ends with, and the auto-deploy tick calls on its
# own. Files that look right prove nothing about currency: something has to be
# running that rewrites them when the host refreshes a token.
PREFLIGHT_UNITS = (
    "songmaker-cli-credentials-mirror.service",
    "songmaker-cli-credentials-mirror.path",
    "songmaker-cli-credentials-mirror.timer",
)


def _run_preflight(
    run_installer, sabotage=None, path: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """The shell entry point the auto-deploy tick calls, in the same sandbox."""
    run_installer()
    if sabotage is not None:
        sabotage()
    environment = run_installer.environment()
    if path is not None:
        environment["PATH"] = path
    return subprocess.run(
        [
            str(run_installer.checkout / "scripts" / "check_agent_cli_mounts.sh"),
            "--home", str(run_installer.home),
            "--mirror-dir", str(run_installer.home / ".songmaker/agent-cli-credentials"),
        ],
        env=environment, text=True, capture_output=True, check=False,
    )


def _run_argumentless_preflight(
    run_installer, sabotage=None,
) -> subprocess.CompletedProcess[str]:
    run_installer()
    if sabotage is not None:
        sabotage()
    return subprocess.run(
        [str(run_installer.checkout / "scripts" / "check_agent_cli_mounts.sh")],
        env=run_installer.environment(), text=True, capture_output=True, check=False,
    )


def _forget(run_installer, fact: str) -> None:
    """Take one line out of the state table the fakes answer from."""
    kept = [
        line for line in run_installer.state.read_text().splitlines()
        if line != fact
    ]
    run_installer.state.write_text("".join(f"{line}\n" for line in kept))


@pytest.mark.parametrize(
    ("cli", "mirror_file"),
    [("claude", "claude.json"), ("grok", "grok.json"), ("codex", "codex.json")],
)
def test_a_missing_credential_file_fails_the_preflight(
    run_installer, cli, mirror_file,
) -> None:
    """Through the shell, not the Python function.

    The verifier call was deleted from this script once and nothing went red:
    its Python tests kept passing while the surface the deploy tick actually
    runs stopped checking anything at all.
    """
    mirrored = run_installer.home / ".songmaker/agent-cli-credentials"

    result = _run_preflight(run_installer, lambda: (mirrored / mirror_file).unlink())

    assert result.returncode == 1
    assert "is missing" in result.stderr


def test_a_hand_copied_login_fails_the_preflight(run_installer) -> None:
    """The invariant the whole arrangement exists for, checked where it counts."""
    mirrored = run_installer.home / ".songmaker/agent-cli-credentials"
    real_login = (run_installer.home / ".claude/.credentials.json").read_text()

    result = _run_preflight(
        run_installer,
        lambda: (mirrored / "claude.json").write_text(real_login),
    )

    assert result.returncode == 1
    assert "renewal token" in result.stderr


def test_a_world_readable_mirror_file_fails_the_preflight(run_installer) -> None:
    mirrored = run_installer.home / ".songmaker/agent-cli-credentials"

    result = _run_preflight(
        run_installer, lambda: (mirrored / "grok.json").chmod(0o644),
    )

    assert result.returncode == 1
    assert "0644" in result.stderr


def test_a_symlinked_mirror_file_fails_the_preflight(run_installer, tmp_path) -> None:
    mirrored = run_installer.home / ".songmaker/agent-cli-credentials"
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("{}")

    def _swap() -> None:
        (mirrored / "codex.json").unlink()
        (mirrored / "codex.json").symlink_to(elsewhere)

    result = _run_preflight(run_installer, _swap)

    assert result.returncode == 1


def test_a_failed_mirror_service_fails_the_preflight(run_installer) -> None:
    """Live triggers and an old valid copy prove nothing about currency."""
    result = _run_preflight(
        run_installer,
        lambda: run_installer.state.write_text(
            run_installer.state.read_text()
            + "failed songmaker-cli-credentials-mirror.service\n",
        ),
    )

    assert result.returncode == 1
    assert "failed state" in result.stderr


def test_the_preflight_says_so_when_it_cannot_ask_systemd(
    run_installer, tmp_path,
) -> None:
    """A minimal PATH with what the script needs — and no systemctl."""
    minimal = tmp_path / "minimal-bin"
    minimal.mkdir()
    for tool in ("dirname", "readlink", "env", "python3", "sed", "grep", "cut",
                 "getent", "id", "head", "cat", "mkdir", "bash"):
        found = shutil.which(tool)
        if found:
            (minimal / tool).symlink_to(found)

    result = _run_preflight(run_installer, path=str(minimal))

    assert result.returncode == 1
    assert "systemctl is not available" in result.stderr


def test_the_preflight_passes_once_everything_is_installed(run_installer) -> None:
    result = _run_preflight(run_installer)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_argumentless_preflight_rejects_a_different_frozen_mirror_dir(
    run_installer,
) -> None:
    service = run_installer.units / "songmaker-cli-credentials-mirror.service"
    expected = run_installer.home / ".songmaker/agent-cli-credentials"
    different = run_installer.home / ".songmaker/different-credentials"

    result = _run_argumentless_preflight(
        run_installer,
        lambda: service.write_text(
            service.read_text().replace(str(expected), str(different)),
        ),
    )

    assert result.returncode == 1
    assert "Spiegel-Installer erneut ausführen" in result.stderr


def test_argumentless_preflight_rejects_a_mirror_dir_changed_in_dotenv(
    run_installer,
) -> None:
    run_installer()
    (run_installer.checkout / ".env").write_text(
        "SONGMAKER_CLI_CREDENTIALS_DIR=/opt/songmaker/credentials\n",
    )

    result = subprocess.run(
        [str(run_installer.checkout / "scripts" / "check_agent_cli_mounts.sh")],
        env=run_installer.environment(), text=True, capture_output=True, check=False,
    )

    assert result.returncode == 1
    assert "Spiegel-Installer erneut ausführen" in result.stderr


def test_argumentless_preflight_accepts_the_installed_mirror_dir(
    run_installer,
) -> None:
    result = _run_argumentless_preflight(run_installer)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_argumentless_preflight_keeps_the_missing_unit_message(
    run_installer,
) -> None:
    service = run_installer.units / "songmaker-cli-credentials-mirror.service"

    result = _run_argumentless_preflight(run_installer, service.unlink)

    assert result.returncode == 1
    assert "is not installed" in result.stderr
    assert "Spiegel-Installer erneut ausführen" not in result.stderr


@pytest.mark.parametrize("unit", PREFLIGHT_UNITS)
def test_an_uninstalled_unit_fails_the_preflight(run_installer, unit) -> None:
    result = _run_preflight(
        run_installer, lambda: (run_installer.units / unit).unlink(),
    )

    assert result.returncode == 1
    assert "is not installed" in result.stderr


@pytest.mark.parametrize("unit", PREFLIGHT_UNITS)
def test_a_disabled_unit_fails_the_preflight(run_installer, unit) -> None:
    result = _run_preflight(
        run_installer, lambda: _forget(run_installer, f"enabled {unit}"),
    )

    assert result.returncode == 1
    assert "not enabled" in result.stderr


@pytest.mark.parametrize(
    "unit",
    [
        "songmaker-cli-credentials-mirror.path",
        "songmaker-cli-credentials-mirror.timer",
    ],
)
def test_a_stopped_trigger_fails_the_preflight(run_installer, unit) -> None:
    """Enabled only says "at the next boot"; nothing triggers the mirror now."""
    result = _run_preflight(
        run_installer, lambda: _forget(run_installer, f"active {unit}"),
    )

    assert result.returncode == 1
    assert "is not running" in result.stderr


def test_it_refuses_to_install_units_that_would_run_as_root(run_installer) -> None:
    """A root login mirrors /root's logins, which are not the operator's."""
    result = run_installer(SUDO_USER="root")

    assert result.returncode == 1
    assert "would run as root" in result.stderr


def test_running_it_twice_changes_nothing_the_second_time(run_installer) -> None:
    run_installer()
    before = {
        path.name: path.read_text() for path in run_installer.units.iterdir()
    }

    result = run_installer()

    assert result.returncode == 0
    assert {p.name: p.read_text() for p in run_installer.units.iterdir()} == before
