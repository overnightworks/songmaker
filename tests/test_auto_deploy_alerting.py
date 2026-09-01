"""When an auto-deploy tick alerts, driven as a real subprocess.

The unit's ``OnFailure=songmaker-alert@%n.service`` turns a non-zero exit
of scripts/auto-deploy.sh into an email (issue #333), so "which ticks exit
non-zero" is this script's alerting contract and is pinned here against
the real script: a copy of it runs against a throwaway git checkout with
its own origin, with ``logger``, ``docker`` and ``date`` replaced by fakes
on PATH. No real deploy, no syslog, no network — and no waiting: the fake
``date`` is the script's only clock, so an hourly repeat is proven by
moving that clock, never by sleeping.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "auto-deploy.sh"
ALERT_CONFIG_LIB = REPO_ROOT / "scripts" / "alert-config.sh"

FAILURE_ALERT_THRESHOLD = 3
# Shorter than the 1h default only to keep the number of ticks a test has
# to drive small; what is under test is that the repeat follows this
# duration rather than a tick count.
ALERT_REPEAT_SECONDS = 600
# Any fixed point in time — the script only ever reads differences.
CLOCK_START_EPOCH = 1_756_000_000

VALID_ALERT_ENV = """\
ALERT_EMAIL_TO='operator@example.com'
SMTP_HOST='smtp.example.com'
SMTP_PORT='587'
SMTP_USER='songmaker@example.com'
SMTP_PASSWORD='correct-horse-battery-staple'
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Checkout:
    """A throwaway deploy target the script under test can be run against."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "checkout"
        self.origin = tmp_path / "origin.git"
        self.log_file = tmp_path / "journal.txt"
        self._bin = tmp_path / "bin"
        self._bin.mkdir()
        self._clock_file = tmp_path / "clock.txt"
        self._clock_file.write_text(str(CLOCK_START_EPOCH))
        self._commits_pushed = 0

        _git(tmp_path, "init", "--bare", "--initial-branch=main", str(self.origin))
        _git(tmp_path, "clone", str(self.origin), str(self.root))
        _git(self.root, "config", "user.email", "test@example.com")
        _git(self.root, "config", "user.name", "Test")

        (self.root / "scripts").mkdir()
        for source in (DEPLOY_SCRIPT, ALERT_CONFIG_LIB):
            copy = self.root / "scripts" / source.name
            copy.write_text(source.read_text())
            copy.chmod(source.stat().st_mode)
        self.deploy_script = self.root / "scripts" / DEPLOY_SCRIPT.name

        (self.root / "README.md").write_text("initial\n")
        # The deploy guard refuses a dirty tree, and the alert config this
        # script reads lives in an untracked .env — exactly as on the host.
        (self.root / ".gitignore").write_text(".env\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-m", "initial")
        _git(self.root, "push", "origin", "main")

        _write_executable(
            self._bin / "logger",
            '#!/bin/bash\nprintf "%s\\n" "$*" >> "$LOG_CAPTURE_FILE"\n',
        )
        _write_executable(
            self._bin / "date",
            "#!/bin/bash\n"
            'if [[ "$1" == "+%s" ]]; then\n'
            '    cat "$FAKE_CLOCK_FILE"\n'
            "else\n"
            '    exec /usr/bin/date "$@"\n'
            "fi\n",
        )
        self.set_active_jobs(0)

    def set_active_jobs(self, count: int) -> None:
        """Stand in for `docker compose exec postgres psql …`."""
        _write_executable(self._bin / "docker", f'#!/bin/bash\necho {count}\n')

    def write_alert_config(self, content: str = VALID_ALERT_ENV) -> None:
        (self.root / ".env").write_text(content)

    def move_main_forward(self) -> None:
        clone = self.root.parent / "pusher"
        if not clone.exists():
            _git(self.root.parent, "clone", str(self.origin), str(clone))
            _git(clone, "config", "user.email", "test@example.com")
            _git(clone, "config", "user.name", "Test")
        _git(clone, "pull", "--ff-only", "origin", "main")
        self._commits_pushed += 1
        (clone / "README.md").write_text(f"moved {self._commits_pushed}\n")
        _git(clone, "commit", "-am", f"move main {self._commits_pushed}")
        _git(clone, "push", "origin", "main")

    def switch_to_work_branch(self) -> None:
        _git(self.root, "checkout", "-B", "work")

    def switch_to_main(self) -> None:
        _git(self.root, "checkout", "main")

    def advance_clock(self, seconds: int) -> None:
        """Let time pass for the script without any passing for the test."""
        self._clock_file.write_text(str(int(self._clock_file.read_text()) + seconds))

    def adopt_current_head_as_deployed(self) -> None:
        """Skip the first-run adoption tick the script does on a fresh state."""
        self.tick()

    def tick(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.deploy_script)],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                "PATH": f"{self._bin}:/usr/bin:/bin",
                "HOME": str(self.root.parent),
                "LOG_CAPTURE_FILE": str(self.log_file),
                "FAKE_CLOCK_FILE": str(self._clock_file),
                "SONGMAKER_AUTODEPLOY_FAILURE_ALERT_THRESHOLD": str(FAILURE_ALERT_THRESHOLD),
                "SONGMAKER_AUTODEPLOY_ALERT_REPEAT_SECONDS": str(ALERT_REPEAT_SECONDS),
            },
        )

    @property
    def journal(self) -> str:
        return self.log_file.read_text() if self.log_file.exists() else ""

    def alert_lines(self) -> list[str]:
        return [line for line in self.journal.splitlines() if "ALERT:" in line]


@pytest.fixture
def stuck_checkout(tmp_path: Path) -> Checkout:
    """A checkout whose every tick refuses to deploy: HEAD is off main."""
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.switch_to_work_branch()
    return checkout


def test_a_streak_fails_the_unit_only_on_the_tick_that_crosses_the_threshold(
    stuck_checkout: Checkout,
) -> None:
    exit_codes = [stuck_checkout.tick().returncode for _ in range(4)]

    assert exit_codes == [0, 0, 1, 0]
    assert len(stuck_checkout.alert_lines()) == 1


# A tick is not a fixed two minutes: a systemd timer starts no second run
# while the previous one is still going, and one tick may wait out the
# whole compose-up timeout. Both speeds below therefore have to reach the
# operator on the same wall-clock cadence — the fast one without paging
# more often, the slow one without going quiet for hours.
@pytest.mark.parametrize("seconds_per_tick", [60, ALERT_REPEAT_SECONDS])
def test_an_outage_nobody_fixes_is_paged_again_after_the_repeat_time(
    stuck_checkout: Checkout, seconds_per_tick: int,
) -> None:
    for _ in range(FAILURE_ALERT_THRESHOLD):
        stuck_checkout.tick()
    assert len(stuck_checkout.alert_lines()) == 1

    elapsed = 0
    while elapsed < ALERT_REPEAT_SECONDS:
        stuck_checkout.advance_clock(seconds_per_tick)
        elapsed += seconds_per_tick
        result = stuck_checkout.tick()

    assert result.returncode == 1
    assert len(stuck_checkout.alert_lines()) == 2


def test_a_recovered_tick_resets_the_streak(stuck_checkout: Checkout) -> None:
    """And with it the repeat window — no clock is moved below.

    A new outage minutes after a recovered one must page on its own
    crossing tick instead of waiting out the previous episode's hour.
    """
    for _ in range(FAILURE_ALERT_THRESHOLD):
        stuck_checkout.tick()

    stuck_checkout.switch_to_main()
    recovered = stuck_checkout.tick()
    assert recovered.returncode == 0

    stuck_checkout.switch_to_work_branch()
    stuck_checkout.move_main_forward()
    assert [stuck_checkout.tick().returncode for _ in range(3)] == [0, 0, 1]


def test_a_missing_alert_configuration_refuses_to_deploy_and_names_the_key(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    checkout.move_main_forward()
    checkout.write_alert_config(
        VALID_ALERT_ENV.replace("SMTP_PASSWORD='correct-horse-battery-staple'\n", ""),
    )

    result = checkout.tick()

    assert result.returncode == 0
    assert "SMTP_PASSWORD" in checkout.journal
    assert "alert channel not configured" in checkout.journal
