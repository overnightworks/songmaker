from __future__ import annotations

import argparse
import os
import signal
import stat
import subprocess
import sys
import threading
from pathlib import Path

from requirement_binder import (
    BindingResult,
    RequirementBinderError,
    RequirementBinderRecoveryError,
    bind_requirement_revision,
)
from requirement_contract import RequirementContractError
from requirement_witness import (
    LIVE_DEADLINE_SECONDS,
    HttpsGitHubClient,
    LiveWitnessError,
)

WORKER_FLAG = "--private-bind-worker"
WORKER_GUARD_FLAG = "--private-bind-worker-guard-fd"
TERMINATION_GRACE_SECONDS = 5.0


def _arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--issue-number", required=True, type=int)
    parser.add_argument("--comment-id", required=True, type=int)
    parser.add_argument(WORKER_FLAG, action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(WORKER_GUARD_FLAG, type=int, help=argparse.SUPPRESS)
    return parser.parse_args(arguments)


def _worker(arguments: argparse.Namespace) -> int:
    try:
        bind_requirement_revision(
            Path.cwd(),
            arguments.path,
            arguments.issue_number,
            arguments.comment_id,
            HttpsGitHubClient.from_environment(),
            on_prepared=_report_prepared,
        )
    except RequirementBinderRecoveryError as error:
        print(f"Requirement bind recovery required: {error}", file=sys.stderr)
        return 2
    except (RequirementBinderError, RequirementContractError, LiveWitnessError) as error:
        print(f"Requirement bind refused: {error}", file=sys.stderr)
        return 1
    return 0


def _report_prepared(result: BindingResult) -> None:
    print(
        f"Local binding prepared for requirement {result.document} at "
        f"sha256:{result.content_sha256}",
        flush=True,
    )
    print(
        "Review the complete diff, commit and push it, then wait for the live "
        "Requirement witnesses check before treating it as landed.",
        flush=True,
    )


def _supervise(raw_arguments: list[str]) -> int:
    guard_read, guard_write = os.pipe()
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        *raw_arguments,
        WORKER_FLAG,
        WORKER_GUARD_FLAG,
        str(guard_read),
    ]
    try:
        process = subprocess.Popen(
            command,
            cwd=Path.cwd(),
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            shell=False,
            pass_fds=(guard_read,),
        )
    except BaseException:
        os.close(guard_read)
        os.close(guard_write)
        raise
    os.close(guard_read)
    try:
        return process.wait(timeout=LIVE_DEADLINE_SECONDS)
    except subprocess.TimeoutExpired:
        _stop_process_group(process)
        print(
            "Requirement bind exceeded its 120-second wall deadline. The worker "
            "was stopped; inspect the worktree for an original, partial red, or "
            "fully prevalidated state before retrying.",
            file=sys.stderr,
        )
        return 2
    except BaseException:
        _stop_process_group(process)
        raise
    finally:
        os.close(guard_write)


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            process.wait()
            return
        process.wait(timeout=TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        process.wait()


def _start_parent_guard(descriptor: int | None) -> bool:
    if descriptor is None or descriptor < 0:
        return False
    try:
        metadata = os.fstat(descriptor)
    except OSError:
        return False
    if not stat.S_ISFIFO(metadata.st_mode):
        os.close(descriptor)
        return False

    def watch() -> None:
        try:
            while os.read(descriptor, 1):
                pass
        except OSError:
            pass
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        except ProcessLookupError:
            pass

    threading.Thread(target=watch, name="requirement-bind-parent-guard", daemon=True).start()
    return True


def main() -> int:
    arguments = _arguments(sys.argv[1:])
    if arguments.private_bind_worker:
        if not _start_parent_guard(arguments.private_bind_worker_guard_fd):
            print("Requirement bind refused: private worker guard is absent", file=sys.stderr)
            return 1
        return _worker(arguments)
    raw_arguments = [
        "--path",
        arguments.path,
        "--issue-number",
        str(arguments.issue_number),
        "--comment-id",
        str(arguments.comment_id),
    ]
    return _supervise(raw_arguments)


if __name__ == "__main__":
    raise SystemExit(main())
