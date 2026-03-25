"""REST API — aggregates all endpoint sub-routers.

Sub-modules:
    album_api       — album CRUD + cleanup
    song_api        — song + version CRUD
    generation_api  — generation, scoring, rating, pick, job endpoints
    chat_api        — Claude chat, capabilities, generation defaults

Shared helpers live in api_helpers.py.
"""

from __future__ import annotations

from fastapi import APIRouter

from songmaker_cli.admin_api import router as admin_router
from songmaker_cli.album_api import router as album_router
from songmaker_cli.auth_api import router as auth_router
from songmaker_cli.chat_api import router as chat_router
from songmaker_cli.generation_api import router as generation_router
from songmaker_cli.song_api import router as song_router

router = APIRouter(prefix="/api")
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(album_router)
router.include_router(song_router)
router.include_router(generation_router)
router.include_router(chat_router)
