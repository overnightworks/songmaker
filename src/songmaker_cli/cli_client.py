"""HTTP client utilities for the CLI — talks to the songmaker API."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

DEFAULT_SERVER = "http://localhost:8080"
POLL_INTERVAL = 2.0

SESSION_DIR = Path.home() / ".songmaker"
SESSION_FILE = SESSION_DIR / "session.json"


class ServerError(Exception):
    pass


def _load_session(server: str) -> dict:
    """Load saved session cookies for a server, or return empty dict."""
    if not SESSION_FILE.exists():
        return {}
    try:
        data = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return data.get(server, {})
    except (json.JSONDecodeError, OSError):
        return {}


def _save_session(server: str, cookies: dict) -> None:
    """Save session cookies for a server."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if SESSION_FILE.exists():
        try:
            existing = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    existing[server] = cookies
    fd = os.open(str(SESSION_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(existing, indent=2).encode("utf-8"))
    finally:
        os.close(fd)


def _clear_session(server: str) -> None:
    """Remove saved session for a server."""
    if not SESSION_FILE.exists():
        return
    try:
        existing = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        existing.pop(server, None)
        SESSION_FILE.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        pass


def _build_client(server: str) -> httpx.Client:
    """Build an httpx client with stored session cookies."""
    session = _load_session(server)
    cookies = httpx.Cookies()
    for name, value in session.items():
        cookies.set(name, value)
    return httpx.Client(cookies=cookies, timeout=30)


def _extract_cookies(response: httpx.Response) -> dict:
    """Extract cookies from a response as a plain dict."""
    result = {}
    for name, value in response.cookies.items():
        result[name] = value
    return result


def cli_login(server: str, username: str, password: str) -> dict:
    """Authenticate with the server and save the session.

    Returns the user info dict on success, raises ServerError on failure.
    """
    url = f"{server}/api/auth/login"
    try:
        resp = httpx.post(url, json={"username": username, "password": password}, timeout=10)
    except httpx.ConnectError:
        raise ServerError(f"Cannot connect to {server}. Is the server running?")

    if not resp.is_success:
        is_json = resp.headers.get("content-type", "").startswith("application/json")
        detail = resp.json().get("detail", resp.text[:200]) if is_json else resp.text[:200]
        raise ServerError(f"Login failed: {detail}")

    cookies = _extract_cookies(resp)
    _save_session(server, cookies)
    log.info("Session saved to %s", SESSION_FILE)
    return resp.json()


def cli_logout(server: str) -> None:
    """Logout and clear the saved session."""
    try:
        with _build_client(server) as client:
            csrf = client.cookies.get("csrf_token")
            headers = {"X-CSRF-Token": csrf} if csrf else {}
            client.delete(f"{server}/api/auth/session", headers=headers)
    except httpx.ConnectError:
        pass
    _clear_session(server)


def api_get(server: str, path: str) -> dict | list:
    url = f"{server}{path}"
    log.debug("GET %s", url)
    try:
        with _build_client(server) as client:
            resp = client.get(url)
    except httpx.ConnectError:
        raise ServerError(f"Cannot connect to {server}. Is the server running?")
    if resp.status_code == 401:
        raise ServerError("Not authenticated. Run 'songmaker login' first.")
    if not resp.is_success:
        raise ServerError(f"GET {path}: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def api_post(server: str, path: str, json: dict | None = None) -> dict:
    url = f"{server}{path}"
    log.debug("POST %s %s", url, json)
    try:
        with _build_client(server) as client:
            csrf = client.cookies.get("csrf_token")
            headers = {"X-CSRF-Token": csrf} if csrf else {}
            resp = client.post(url, json=json or {}, headers=headers)
    except httpx.ConnectError:
        raise ServerError(f"Cannot connect to {server}. Is the server running?")
    if resp.status_code == 401:
        raise ServerError("Not authenticated. Run 'songmaker login' first.")
    if not resp.is_success:
        raise ServerError(f"POST {path}: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def api_put(server: str, path: str, json: dict) -> dict:
    url = f"{server}{path}"
    log.debug("PUT %s %s", url, json)
    try:
        with _build_client(server) as client:
            csrf = client.cookies.get("csrf_token")
            headers = {"X-CSRF-Token": csrf} if csrf else {}
            resp = client.put(url, json=json, headers=headers)
    except httpx.ConnectError:
        raise ServerError(f"Cannot connect to {server}. Is the server running?")
    if resp.status_code == 401:
        raise ServerError("Not authenticated. Run 'songmaker login' first.")
    if not resp.is_success:
        raise ServerError(f"PUT {path}: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def api_upload(
    server: str, path: str, files: list[tuple[str, tuple[str, bytes, str]]],
) -> dict:
    url = f"{server}{path}"
    log.debug("POST (upload) %s", url)
    try:
        with _build_client(server) as client:
            csrf = client.cookies.get("csrf_token")
            headers = {"X-CSRF-Token": csrf} if csrf else {}
            resp = client.post(url, files=files, headers=headers)
    except httpx.ConnectError:
        raise ServerError(f"Cannot connect to {server}. Is the server running?")
    if resp.status_code == 401:
        raise ServerError("Not authenticated. Run 'songmaker login' first.")
    if not resp.is_success:
        raise ServerError(f"POST {path}: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def resolve_song(server: str, query: str) -> dict:
    response = api_get(server, "/api/songs")
    songs = response["items"] if isinstance(response, dict) else response
    query_lower = query.lower()

    exact = [s for s in songs if s["title"].lower() == query_lower]
    if len(exact) == 1:
        return exact[0]

    partial = [s for s in songs if query_lower in s["title"].lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        titles = ", ".join(f"'{s['title']}'" for s in partial[:5])
        raise ServerError(f"Multiple matches for '{query}': {titles}. Be more specific.")

    raise ServerError(f"No song found matching '{query}'")


def poll_job(server: str, job_id: str) -> dict:
    while True:
        job = api_get(server, f"/api/jobs/{job_id}")
        status = job["status"]
        progress = job.get("progress", 0)

        if status == "completed":
            _print_progress(1.0, "completed")
            print()
            return job
        if status == "failed":
            _print_progress(progress, "failed")
            print()
            error = job.get("error", "Unknown error")
            raise ServerError(f"Job failed: {error}")

        _print_progress(progress, status)
        time.sleep(POLL_INTERVAL)


def _print_progress(progress: float, status: str) -> None:
    pct = int(progress * 100)
    bar_len = 30
    filled = int(bar_len * progress)
    bar = "\u2588" * filled + "\u2591" * (bar_len - filled)
    sys.stderr.write(f"\r  [{bar}] {pct}% {status}")
    sys.stderr.flush()
