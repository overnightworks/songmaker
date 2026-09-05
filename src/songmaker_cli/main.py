"""Songmaker CLI — thin HTTP client that talks to the songmaker API."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Annotated, Optional

from cyclopts import App, Parameter

from songmaker_cli.cli_client import (
    DEFAULT_SERVER,
    ServerError,
    api_get,
    api_post,
    api_put,
    cli_login,
    cli_logout,
    poll_job,
    resolve_song,
)
from songmaker_cli.errors import SongmakerError
from songmaker_cli.logging_config import configure_cli_logging

log = logging.getLogger(__name__)

app = App(name="songmaker", help="AI-powered song generation platform.")


@app.meta.default
def _launcher(
    *tokens: Annotated[str, Parameter(show=False, allow_leading_hyphen=True)],
    verbose: Annotated[bool, Parameter(name=["-v", "--verbose"], help="Debug logging")] = False,
    quiet: Annotated[bool, Parameter(name=["-q", "--quiet"], help="Errors only")] = False,
    server: Annotated[
        str, Parameter(name=["-s", "--server"], help="Server URL"),
    ] = DEFAULT_SERVER,
) -> None:
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    configure_cli_logging(level)
    global _server_url
    _server_url = server
    app(tokens)


_server_url: str = DEFAULT_SERVER


def _server() -> str:
    return _server_url


# ── Auth ────────────────────────────────────────────────────────────


@app.command
def login(
    username: Annotated[str, Parameter(help="Username")],
    password: Annotated[str, Parameter(help="Password")],
) -> None:
    """Authenticate with the songmaker server and save the session."""
    user = cli_login(_server(), username, password)
    log.info("Logged in as '%s' (role=%s)", user["username"], user["role"])


@app.command
def logout() -> None:
    """Logout and clear the saved session."""
    cli_logout(_server())
    log.info("Logged out")


# ── Server ──────────────────────────────────────────────────────────


@app.command
def server(
    port: Annotated[int, Parameter(help="Server port")] = 8080,
    root: Annotated[Optional[str], Parameter(help="Project root")] = None,
    open_browser: Annotated[
        bool, Parameter(name="--open", help="Open browser on start"),
    ] = False,
) -> None:
    """Start the songmaker web server."""
    from songmaker_cli.server import run_server

    project_root = Path(root).resolve() if root else None
    run_server(project_root=project_root, port=port, open_browser=open_browser)


# ── Auth (local DB commands) ────────────────────────────────────────


@app.command(name="reset-password")
def reset_password(
    username: Annotated[str, Parameter(help="Username to reset")],
    password: Annotated[str, Parameter(help="New password (min 8 chars)")],
) -> None:
    """Reset a user's password (requires local DB access)."""
    from songmaker_cli.auth import (
        MIN_PASSWORD_LENGTH,
        check_password_strength,
        hash_password,
    )
    from songmaker_cli.db.engine import init_db, resolve_database_url

    if len(password) < MIN_PASSWORD_LENGTH:
        print(f"Error: password must be at least {MIN_PASSWORD_LENGTH} characters")
        sys.exit(1)
    try:
        check_password_strength(password)
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    db_url = resolve_database_url()

    factory = init_db(db_url)
    with factory() as session:
        from songmaker_cli.db.queries import get_user_by_username
        user = get_user_by_username(session, username)
        if not user:
            print(f"Error: user '{username}' not found")
            sys.exit(1)
        user.password_hash = hash_password(password)
        session.commit()
        print(f"Password reset for '{username}' (role={user.role})")


@app.command(name="list-users")
def list_users_cmd() -> None:
    """List all users (requires local DB access)."""
    from songmaker_cli.db.engine import init_db, resolve_database_url
    from songmaker_cli.db.queries import list_users

    db_url = resolve_database_url()

    factory = init_db(db_url)
    with factory() as session:
        users = list_users(session)
        if not users:
            print("No users found. Run the server and visit /setup to create an admin.")
            return
        for u in users:
            status = "active" if u.is_active else "disabled"
            print(f"  {u.username}  role={u.role}  {status}")


# ── Albums ──────────────────────────────────────────────────────────


@app.command
def albums() -> None:
    """List all albums."""
    data = api_get(_server(), "/api/albums")["items"]
    for album in data:
        count = album.get("song_count", 0)
        print(f"  {album['title']} ({album['artist']}) — {count} songs")


# ── Songs ───────────────────────────────────────────────────────────


@app.command
def songs(
    album: Annotated[Optional[str], Parameter(help="Filter by album title")] = None,
) -> None:
    """List all songs, optionally filtered by album."""
    s = _server()
    path = "/api/songs"
    if album:
        albums_data = api_get(s, "/api/albums")["items"]
        match = next((a for a in albums_data if album.lower() in a["title"].lower()), None)
        if not match:
            raise ServerError(f"Album not found: '{album}'")
        path += f"?album_id={match['id']}"

    data = api_get(s, path)["items"]
    for song in data:
        gens = song.get("generation_count", 0)
        print(f"  {song['title']} [{song['album_title']}] — {gens} generations")


@app.command
def song(
    query: Annotated[str, Parameter(help="Song title (fuzzy match)")],
) -> None:
    """Show details for a song."""
    s = _server()
    matched = resolve_song(s, query)
    print(f"Title:    {matched['title']}")
    print(f"Album:    {matched['album_title']} ({matched['artist']})")
    print(f"BPM:      {matched['bpm']}")
    print(f"Duration: {matched['duration']}s")
    print(f"Key:      {matched['key']}")
    print(f"Versions: {matched['version_count']}")
    print(f"Gens:     {matched['generation_count']}")
    if matched.get("generation_params"):
        print(f"Params:   {json.dumps(matched['generation_params'])}")
    if matched.get("best_scores"):
        for k, v in matched["best_scores"].items():
            if isinstance(v, (int, float)):
                print(f"  {k}: {v}")


# ── Generate ────────────────────────────────────────────────────────


@app.command
def generate(
    query: Annotated[str, Parameter(help="Song title (fuzzy match)")],
    model: Annotated[
        str, Parameter(name=["-m", "--model"], help="Model mode (e.g. sft, turbo, xl-sft)"),
    ],
    count: Annotated[int, Parameter(name=["-n", "--count"], help="Number of generations")] = 1,
) -> None:
    """Queue a generation job for a song."""
    s = _server()
    matched = resolve_song(s, query)
    log.info("Generating %dx for '%s' (model=%s)...", count, matched["title"], model)

    job = api_post(
        s, f"/api/songs/{matched['id']}/generate",
        {"count": count, "model": model},
    )
    poll_job(s, job["id"])
    log.info("Done.")


# ── Score ───────────────────────────────────────────────────────────


@app.command
def score(
    query: Annotated[str, Parameter(help="Song title (fuzzy match)")],
    generation: Annotated[
        Optional[int], Parameter(name=["-g", "--generation"], help="Generation number"),
    ] = None,
) -> None:
    """Score a generation. Defaults to the latest."""
    s = _server()
    matched = resolve_song(s, query)
    gens = matched.get("generations", [])
    if not gens:
        raise ServerError(f"No generations for '{matched['title']}'")

    if generation is not None:
        gen = next((g for g in gens if g["generation_number"] == generation), None)
        if not gen:
            raise ServerError(f"Generation #{generation} not found")
    else:
        gen = gens[0]

    log.info("Scoring generation #%d of '%s'...", gen["generation_number"], matched["title"])
    job = api_post(s, f"/api/generations/{gen['id']}/score")
    poll_job(s, job["id"])
    log.info("Done.")


# ── Edit ────────────────────────────────────────────────────────────


@app.command
def edit(
    query: Annotated[str, Parameter(help="Song title (fuzzy match)")],
    lyrics: Annotated[Optional[str], Parameter(help="New lyrics (or @file.txt)")] = None,
    prompt: Annotated[Optional[str], Parameter(help="New style prompt")] = None,
    bpm: Annotated[Optional[int], Parameter(help="BPM")] = None,
    duration: Annotated[Optional[int], Parameter(help="Duration in seconds")] = None,
    key: Annotated[Optional[str], Parameter(help="Musical key")] = None,
) -> None:
    """Edit a song's content (creates a new version)."""
    s = _server()
    matched = resolve_song(s, query)

    params: dict = {}
    if lyrics is not None:
        if lyrics.startswith("@"):
            params["lyrics"] = Path(lyrics[1:]).read_text(encoding="utf-8")
        else:
            params["lyrics"] = lyrics
    if prompt is not None:
        params["prompt"] = prompt
    if bpm is not None:
        params["bpm"] = bpm
    if duration is not None:
        params["audio_duration"] = duration
    if key is not None:
        params["key_scale"] = key

    if not params:
        raise ServerError("No changes specified")

    updated = api_put(s, f"/api/songs/{matched['id']}", params)
    log.info("Updated '%s' → v%d", updated["title"], updated["version_count"])


# ── Reimport ──────────────────────────────────────────────────────────


@app.command
def reimport(
    file: Annotated[str, Parameter(help="MP3 or WAV file to reimport")],
    song_id: Annotated[str, Parameter(name="--song", help="Song ID to attach to")],
    wav: Annotated[Optional[str], Parameter(name="--wav", help="Additional WAV file")] = None,
) -> None:
    """Reimport an MP3/WAV file into an existing song."""
    import mimetypes

    s = _server()
    file_path = Path(file)
    if not file_path.exists():
        raise ServerError(f"File not found: {file}")

    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    files: list[tuple[str, tuple[str, bytes, str]]] = []

    if file_path.suffix.lower() == ".wav":
        files.append(("wav", (file_path.name, file_path.read_bytes(), mime)))
    else:
        files.append(("mp3", (file_path.name, file_path.read_bytes(), mime)))

    if wav:
        wav_path = Path(wav)
        if not wav_path.exists():
            raise ServerError(f"WAV file not found: {wav}")
        wav_mime = mimetypes.guess_type(wav_path.name)[0] or "audio/wav"
        files.append(("wav", (wav_path.name, wav_path.read_bytes(), wav_mime)))

    from songmaker_cli.cli_client import api_upload
    result = api_upload(s, f"/api/songs/{song_id}/reimport", files)
    log.info("Reimported as generation #%s", result.get("generation_number", "?"))


# ── Main ────────────────────────────────────────────────────────────


def main() -> None:
    try:
        app.meta()
    except (SongmakerError, ServerError) as exc:
        log.exception("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
