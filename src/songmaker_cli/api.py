"""REST API — aggregates all endpoint sub-routers.

Sub-modules:
    album_api       — album CRUD + cleanup
    song_api        — song + version CRUD
    generation_api  — generation, scoring, rating, pick, job endpoints
    chat_api        — Claude chat, capabilities
    settings_api    — generation presets, builtins, global defaults

Shared helpers live in api_helpers.py.
"""

from __future__ import annotations

from fastapi import APIRouter

from songmaker_cli.admin_api import router as admin_router
from songmaker_cli.album_api import router as album_router
from songmaker_cli.auth_api import router as auth_router
from songmaker_cli.chat_api import router as chat_router
from songmaker_cli.conversation_api import router as conversation_router
from songmaker_cli.generation_api import router as generation_router
from songmaker_cli.internal_api import router as internal_router
from songmaker_cli.library_api import router as library_router
from songmaker_cli.lora_api import router as lora_router
from songmaker_cli.playlist_api import router as playlist_router
from songmaker_cli.queue_stream_api import router as queue_stream_router
from songmaker_cli.reimport_api import router as reimport_router
from songmaker_cli.settings_api import router as settings_router
from songmaker_cli.song_api import router as song_router

router = APIRouter(prefix="/api")
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(album_router)
router.include_router(song_router)
router.include_router(library_router)
router.include_router(generation_router)
router.include_router(internal_router)
router.include_router(lora_router)
router.include_router(playlist_router)
router.include_router(queue_stream_router)
router.include_router(reimport_router)
router.include_router(chat_router)
router.include_router(conversation_router)
router.include_router(settings_router)
