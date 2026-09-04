"""Structured logging setup via structlog wrapping stdlib."""

from __future__ import annotations

import logging

import structlog

from songmaker_cli.settings import get_settings


class _SongmakerLogHandler(logging.StreamHandler):
    """The root handler installed by :func:`configure_logging`."""


class _SongmakerCliLogHandler(logging.StreamHandler):
    """The temporary root handler installed before a CLI command runs."""


def configure_cli_logging(level: int) -> None:
    """Configure the CLI's plain logging until a command selects another format."""
    logging.basicConfig(
        level=level,
        format="%(name)s: %(message)s",
        handlers=[_SongmakerCliLogHandler()],
    )


def configure_logging() -> None:
    """Configure structlog as a processor pipeline over stdlib logging.

    Settings.log_format=json  -> JSON lines (production).
    Settings.log_format=text  -> colored human-readable (default, dev).
    """
    json_mode = get_settings().log_format == "json"

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_mode:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    handler = _SongmakerLogHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    for existing_handler in root.handlers[:]:
        if isinstance(existing_handler, (_SongmakerCliLogHandler, _SongmakerLogHandler)):
            root.removeHandler(existing_handler)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
