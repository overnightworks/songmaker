"""Entry point of the arq workers: `python -m songmaker_cli.arq_worker <settings path>`."""

import asyncio
import sys

from arq.cli import cli

# arq's own dictConfig would add a plain-text handler beside logline's JSON one, which
# the worker's `configure` installs; this one changes nothing.
UNCONFIGURED_LOGGING = {"version": 1, "disable_existing_loggers": False}


def main() -> None:
    # arq 0.27 reads the current loop in Worker.__init__; Python 3.14 no longer creates one.
    asyncio.set_event_loop(asyncio.new_event_loop())
    cli(args=[*sys.argv[1:], "--custom-log-dict", "songmaker_cli.arq_worker.UNCONFIGURED_LOGGING"])


if __name__ == "__main__":
    main()
