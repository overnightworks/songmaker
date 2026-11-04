"""The deploy tick refuses a release whose declared secret files are not in place."""

from __future__ import annotations

from pathlib import Path

from auto_deploy_harness import Checkout
from auto_deploy_support import FAILURE_ALERT_THRESHOLD


def test_a_release_declaring_a_missing_secret_file_is_refused_before_build_and_recreate(
    tmp_path: Path,
) -> None:
    checkout = Checkout(tmp_path)
    checkout.write_alert_config()
    checkout.adopt_current_head_as_deployed()
    deployed_before = checkout.deployed_sha_file.read_text()
    declared = tmp_path / ".secrets" / "songmaker" / "session-secret"
    checkout.set_compose_secret_files({"session-secret": declared})
    checkout.move_main_forward()

    exit_codes = [checkout.tick().returncode for _ in range(FAILURE_ALERT_THRESHOLD)]

    assert exit_codes == [0, 0, 1]
    assert len(checkout.alert_lines()) == 1
    assert "reason: declared secret files refused" in checkout.journal
    assert "session-secret is declared but missing" in checkout.journal
    assert checkout.build_and_recreate_calls == []
    assert checkout.deployed_sha_file.read_text() == deployed_before
