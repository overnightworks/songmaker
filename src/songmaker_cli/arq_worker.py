"""Entry point of the arq workers: `python -m songmaker_cli.arq_worker <settings path>`."""

import asyncio

from arq.cli import cli


def main() -> None:
    # arq 0.27 reads the current loop in Worker.__init__; Python 3.14 no longer creates one.
    cli()


if __name__ == "__main__":
    main()
