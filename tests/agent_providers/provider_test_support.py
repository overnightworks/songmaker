"""Library-local test support for the ``agent_providers`` package tests.

A sibling ``conftest.py`` in this directory would make ``from conftest import``
ambiguous under pytest's prepend import mode — the root ``tests/conftest.py``
and this package's own ``conftest.py`` both import as ``conftest``. The lib
tests therefore reach their shared helpers here, by basename, which resolves
the same way both inside songmaker today and inside the extracted
``agent_providers`` repository tomorrow (issue #825, S1).

Self-contained by design: it imports only ``agent_providers`` and the standard
library, never ``songmaker_cli``. The deployment facts below are the package's
own sample — a host named ``songmaker`` with its twelve co-writer tools — not
an import of the application's constants, so the tests prove the provider layer
against values this package owns.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

from agent_providers.config import (
    ProviderRuntimeConfig,
    configure,
    current_config,
    reset_config,
)
from agent_providers.tools import ToolCatalog, ToolDeclaration

_fake_cli_processes: list[MagicMock] = []


def fake_cli_process(
    first_line: bytes | None, *, still_running: bool = False, stdin_blocked: bool = False,
) -> MagicMock:
    """Build a pipe-backed stand-in for the ``subprocess.Popen`` CLI handle."""
    proc = MagicMock()
    proc.pid = 4343
    proc.poll.return_value = None if still_running else 0
    stdin_reader, stdin_writer = os.pipe()
    stdout_reader, stdout_writer = os.pipe()
    stderr_reader, stderr_writer = os.pipe()
    proc.stdin = os.fdopen(stdin_writer, "wb", buffering=0)
    proc.stdout = os.fdopen(stdout_reader, "rb", buffering=0)
    proc.stderr = os.fdopen(stderr_reader, "rb", buffering=0)
    proc._stdin_reader = os.fdopen(stdin_reader, "rb", buffering=0)
    proc._stdout_writer = os.fdopen(stdout_writer, "wb", buffering=0)
    proc._stderr_writer = os.fdopen(stderr_writer, "wb", buffering=0)
    proc._stderr_writer.close()
    if stdin_blocked:
        os.set_blocking(proc.stdin.fileno(), False)
        try:
            while True:
                os.write(proc.stdin.fileno(), b"x" * 65536)
        except BlockingIOError:
            pass
    if first_line is not None:
        proc._stdout_writer.write(first_line)
        proc._stdout_writer.close()
    proc.wait.return_value = None
    _fake_cli_processes.append(proc)
    return proc


def close_fake_cli_pipes() -> None:
    """Close every pipe-backed fake CLI stream built during a test module."""
    for proc in _fake_cli_processes:
        for stream_name in (
            "stdin", "stdout", "stderr", "_stdin_reader", "_stdout_writer", "_stderr_writer",
        ):
            stream = getattr(proc, stream_name)
            if not stream.closed:
                stream.close()
    _fake_cli_processes.clear()


def override_provider_runtime(**deployment_facts: Any) -> None:
    """Replace named provider deployment facts for the current test only.

    Deliberately replaces the installation rather than adding to it, because
    ``configure()`` refuses a differing second value; ``reset_config`` first,
    then install the merged replacement.
    """
    replacement = ProviderRuntimeConfig(
        **{**current_config().model_dump(), **deployment_facts},
    )
    reset_config()
    configure(replacement)


def use_codex_process_pool(monkeypatch, process_pool) -> None:
    """Give every Codex module that admits a process the same test pool."""
    from agent_providers.codex import image, protocol, transport

    for module in (image, protocol, transport):
        monkeypatch.setattr(module, "get_codex_process_pool", lambda: process_pool)


SECRET_ENV_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "SESSION_SECRET",
    "SONGMAKER_INTERNAL_TOKEN",
    "DATABASE_URL",
    "REDIS_URL",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "HF_TOKEN",
    "ADMIN_USERNAME",
    "ADMIN_PASSWORD",
    "GRAFANA_USER",
    "GRAFANA_PASSWORD",
)

MCP_TOOL_NAMES: frozenset[str] = frozenset({
    "list_albums",
    "list_songs",
    "search_songs",
    "get_song",
    "get_version",
    "get_generation",
    "create_song",
    "update_song_lyrics",
    "update_song_prompt",
    "update_song_style",
    "rename_song",
    "suggest_album_cover",
})

_STRING = {"type": "string"}
_INT = {"type": "integer"}


def _object(
    properties: dict[str, Any], required: list[str] | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


COWRITER_TOOL_CATALOG: ToolCatalog = ToolCatalog(
    tools=(
        ToolDeclaration(
            name="list_albums",
            description="List all albums owned by the current user.",
            parameters=_object({}),
        ),
        ToolDeclaration(
            name="list_songs",
            description=(
                "List songs. Without album_id, every owned song; "
                "with album_id, that album."
            ),
            parameters=_object({"album_id": _STRING}),
        ),
        ToolDeclaration(
            name="search_songs",
            description="Search songs by title substring. Limit defaults to 20, max 50.",
            parameters=_object({"query": _STRING, "limit": _INT}, ["query"]),
        ),
        ToolDeclaration(
            name="get_song",
            description="Read the full state of a song.",
            parameters=_object({"song_id": _STRING}, ["song_id"]),
        ),
        ToolDeclaration(
            name="get_version",
            description="Read a specific version snapshot of a song.",
            parameters=_object(
                {"song_id": _STRING, "version_id": _STRING}, ["song_id", "version_id"],
            ),
        ),
        ToolDeclaration(
            name="get_generation",
            description="Read a generation's metadata, scores, whisper transcript, and rating.",
            parameters=_object({"generation_id": _STRING}, ["generation_id"]),
        ),
        ToolDeclaration(
            name="create_song",
            description="Create a new song in an album.",
            parameters=_object(
                {
                    "album_id": _STRING,
                    "title": _STRING,
                    "lyrics": _STRING,
                    "prompt": _STRING,
                },
                ["album_id", "title"],
            ),
        ),
        ToolDeclaration(
            name="update_song_lyrics",
            description="Replace the song's current lyrics.",
            parameters=_object({"song_id": _STRING, "lyrics": _STRING}, ["song_id", "lyrics"]),
        ),
        ToolDeclaration(
            name="update_song_prompt",
            description="Replace the song's current style prompt.",
            parameters=_object({"song_id": _STRING, "prompt": _STRING}, ["song_id", "prompt"]),
        ),
        ToolDeclaration(
            name="update_song_style",
            description="Update bpm, key_scale, and/or audio_duration.",
            parameters=_object(
                {
                    "song_id": _STRING,
                    "bpm": _INT,
                    "key_scale": _STRING,
                    "audio_duration": _INT,
                },
                ["song_id"],
            ),
        ),
        ToolDeclaration(
            name="rename_song",
            description="Rename a song's title.",
            parameters=_object({"song_id": _STRING, "title": _STRING}, ["song_id", "title"]),
        ),
        ToolDeclaration(
            name="suggest_album_cover",
            description=(
                "Request three album cover suggestions. "
                "Returns the queued job ID and status."
            ),
            parameters=_object({"album_id": _STRING}, ["album_id"]),
        ),
    ),
)
