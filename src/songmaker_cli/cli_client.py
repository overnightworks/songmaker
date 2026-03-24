"""HTTP client utilities for the CLI — talks to the songmaker API."""

from __future__ import annotations

import logging
import sys
import time

import httpx

log = logging.getLogger(__name__)

DEFAULT_SERVER = "http://localhost:8080"
POLL_INTERVAL = 2.0


class ServerError(Exception):
    pass


def api_get(server: str, path: str) -> dict | list:
    url = f"{server}{path}"
    log.debug("GET %s", url)
    try:
        resp = httpx.get(url, timeout=10)
    except httpx.ConnectError:
        raise ServerError(f"Cannot connect to {server}. Is the server running?")
    if not resp.is_success:
        raise ServerError(f"GET {path}: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def api_post(server: str, path: str, json: dict | None = None) -> dict:
    url = f"{server}{path}"
    log.debug("POST %s %s", url, json)
    try:
        resp = httpx.post(url, json=json or {}, timeout=30)
    except httpx.ConnectError:
        raise ServerError(f"Cannot connect to {server}. Is the server running?")
    if not resp.is_success:
        raise ServerError(f"POST {path}: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def api_put(server: str, path: str, json: dict) -> dict:
    url = f"{server}{path}"
    log.debug("PUT %s %s", url, json)
    try:
        resp = httpx.put(url, json=json, timeout=10)
    except httpx.ConnectError:
        raise ServerError(f"Cannot connect to {server}. Is the server running?")
    if not resp.is_success:
        raise ServerError(f"PUT {path}: {resp.status_code} {resp.text[:200]}")
    return resp.json()


def resolve_song(server: str, query: str) -> dict:
    songs = api_get(server, "/api/songs")
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
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stderr.write(f"\r  [{bar}] {pct}% {status}")
    sys.stderr.flush()
