"""Wire models for the transient playback recorder's upload (#1187)."""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, Field

PLAYBACK_DIAGNOSTICS_MAX_EVENTS: Final = 500
PLAYBACK_DIAGNOSTIC_DETAIL_MAX_LENGTH: Final = 200
PLAYBACK_DIAGNOSTICS_SESSION_ID_MAX_LENGTH: Final = 64
PLAYBACK_DIAGNOSTICS_USER_AGENT_MAX_LENGTH: Final = 512
HTML_MEDIA_READY_STATE_MAX: Final = 4
TAKE_ID_PATTERN: Final = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class PlaybackDiagnosticKind(StrEnum):
    PROMOTE = "promote"
    FRESH_LOAD = "fresh_load"
    PLAY = "play"
    PLAY_REJECTED = "play_rejected"
    PAUSE = "pause"
    ENDED = "ended"
    WAITING = "waiting"
    STALLED = "stalled"
    ERROR = "error"
    RETRY = "retry"
    GIVE_UP = "give_up"
    VISIBILITY_CHANGE = "visibility_change"
    PAGE_HIDE = "page_hide"
    PAGE_SHOW = "page_show"
    FREEZE = "freeze"
    RESUME = "resume"
    TIMER_GAP = "timer_gap"
    MEDIA_SESSION_ACTION = "media_session_action"


class PlaybackDiagnosticEvent(BaseModel):
    at_ms: int = Field(ge=0)
    kind: PlaybackDiagnosticKind
    take_id: str | None = Field(pattern=TAKE_ID_PATTERN)
    position: float = Field(ge=0)
    ready_state: int = Field(ge=0, le=HTML_MEDIA_READY_STATE_MAX)
    deck: Literal["active", "standby"]
    visibility: Literal["visible", "hidden"]
    detail: str = Field(max_length=PLAYBACK_DIAGNOSTIC_DETAIL_MAX_LENGTH)


class PlaybackDiagnosticsReport(BaseModel):
    session_id: str = Field(min_length=1, max_length=PLAYBACK_DIAGNOSTICS_SESSION_ID_MAX_LENGTH)
    user_agent: str = Field(max_length=PLAYBACK_DIAGNOSTICS_USER_AGENT_MAX_LENGTH)
    mse_mp3_supported: bool
    was_discarded: bool
    events: list[PlaybackDiagnosticEvent] = Field(max_length=PLAYBACK_DIAGNOSTICS_MAX_EVENTS)
