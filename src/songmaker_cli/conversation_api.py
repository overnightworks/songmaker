"""Conversation + new-flow chat endpoints (co-writer redesign).

This module owns the Phase 3 conversation-scoped chat API:

- ``POST /chat/turn`` — one turn in the user's active conversation, run by the agent service.
- ``GET /conversations`` — list all the user's conversations.
- ``GET /conversations/{id}`` — full message history of one.
- ``POST /conversations/new`` — archive the active one and start fresh.
- ``DELETE /conversations/{id}`` — wipe a conversation.
- ``GET /memory`` / ``PUT /memory/...`` — durable user, song, and album notes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Final

from agent_runtime_client.wire import TurnMessage
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker
from webauth.config import installed_web_auth_config
from webauth.dependencies import session_id_from_request
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_helpers import (
    check_album_access,
    check_generation_access,
    check_song_access,
    create_job_with_rate_limit,
    owner_filter,
)
from songmaker_cli.api_models import (
    ChatMessageResponse,
    ChatTurnFailureFrame,
    ChatTurnFinalFrame,
    ChatTurnProblem,
    ChatTurnProblemFrame,
    ChatTurnV2Request,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    MemoryBundleResponse,
    MemoryScopeResponse,
    MemoryUpdateRequest,
    StatusResponse,
)
from songmaker_cli.api_models.songs import score_values
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.constants import (
    CURRENT_SONG_FRESHNESS_NOTE,
    JOB_ACTIVE_STATUSES,
    MEMORY_SCOPE_ALBUM,
    MEMORY_SCOPE_SONG,
    MEMORY_SCOPE_USER,
    TURN_BLOCK_ALBUM_NOTES,
    TURN_BLOCK_CURRENT_SONG,
    TURN_BLOCK_CURRENT_TAKE,
    TURN_BLOCK_MENTIONED_ALBUM,
    TURN_BLOCK_MENTIONED_SONGS,
    TURN_BLOCK_MENTIONED_VERSIONS,
    TURN_BLOCK_NO_TAKE,
    TURN_BLOCK_SONG_MEMORY,
    TURN_BLOCK_USER_MEMORY,
    JobStatus,
    JobType,
)
from songmaker_cli.cowriter.history import compact_conversation, count_tokens, fold_summary
from songmaker_cli.cowriter.service_turn import (
    TurnAnswer,
    TurnCaller,
    TurnProblem,
    run_cowriter_turn,
)
from songmaker_cli.db.models import ChatMessage, Conversation, Generation, Song
from songmaker_cli.db.queries.albums import get_album
from songmaker_cli.db.queries.conversations import (
    append_message,
    archive_conversation,
    create_conversation,
    delete_conversation,
    get_active_conversation,
    get_conversation,
    get_or_create_active_conversation,
    list_messages,
    recent_conversations,
    upsert_summary,
)
from songmaker_cli.db.queries.jobs import (
    JobStatusUpdate,
    count_user_active_jobs,
    recover_stale_jobs_by_type,
    update_job_status,
)
from songmaker_cli.db.queries.memory import (
    get_album_memory,
    get_song_memory,
    get_user_memory,
    upsert_album_memory,
    upsert_song_memory,
    upsert_user_memory,
)
from songmaker_cli.db.queries.playlists import best_playable_generation
from songmaker_cli.db.queries.settings import get_cowriter_tail_token_budget
from songmaker_cli.db.queries.songs import list_songs
from songmaker_cli.db.queries.versions import get_version

log = logging.getLogger(__name__)

router = APIRouter()


@dataclass(frozen=True)
class TurnContextBlock:
    name: str
    body: str
    preface: str | None = None

    def render(self) -> str:
        tagged = f"<{self.name}>\n{self.body}\n</{self.name}>"
        if self.preface is None:
            return tagged
        return f"{self.preface}\n{tagged}"


@dataclass(frozen=True)
class TurnContextEnvelope:
    blocks: tuple[TurnContextBlock, ...]

    def wrap_user_message(self, message: str) -> str:
        parts = [block.render() for block in self.blocks]
        parts.append(message)
        return "\n\n".join(parts)

    def names(self) -> list[str]:
        return [block.name for block in self.blocks]

    def body_for(self, name: str) -> str | None:
        for block in self.blocks:
            if block.name == name:
                return block.body
        return None


def _format_current_song(song) -> str:
    parts = [
        f"id: {song.id}",
        f"title: {song.title}",
        f"album: {song.album.title if song.album else ''}",
    ]
    v = song.latest_version
    if v:
        if v.prompt:
            parts.append(f"style: {v.prompt}")
        if v.key_scale:
            parts.append(f"key: {v.key_scale}")
        if v.bpm:
            parts.append(f"bpm: {v.bpm}")
        if v.audio_duration:
            parts.append(f"duration: {v.audio_duration}s")
        if v.lyrics:
            parts.append(f"lyrics:\n{v.lyrics}")
    return "\n".join(parts)


def compose_turn_context(
    *,
    current_song: Song | None,
    user_memory_body: str,
    song_memory_body: str | None,
    album_notes_body: str | None,
    extra_blocks: Sequence[TurnContextBlock] = (),
) -> TurnContextEnvelope:
    """Assemble the provider-neutral turn envelope.

    Current song, memory scopes, and later mention/take blocks are wrapped
    here once. Providers must pass the result through unchanged.
    """
    blocks: list[TurnContextBlock] = []
    if current_song is not None:
        blocks.append(
            TurnContextBlock(
                TURN_BLOCK_CURRENT_SONG,
                _format_current_song(current_song),
                preface=CURRENT_SONG_FRESHNESS_NOTE,
            )
        )
    blocks.append(TurnContextBlock(TURN_BLOCK_USER_MEMORY, user_memory_body))
    if current_song is not None:
        blocks.append(
            TurnContextBlock(
                TURN_BLOCK_SONG_MEMORY,
                song_memory_body or "",
            )
        )
        if album_notes_body:
            blocks.append(
                TurnContextBlock(
                    TURN_BLOCK_ALBUM_NOTES,
                    album_notes_body,
                )
            )
    blocks.extend(extra_blocks)
    names = [block.name for block in blocks]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate turn-context block names: {names}")
    return TurnContextEnvelope(tuple(blocks))


def load_memory_for_turn(
    session: Session,
    user_id: str,
    current_song: Song | None,
) -> tuple[str, str | None, str | None]:
    user_row = get_user_memory(session, user_id)
    user_body = user_row.body if user_row else ""
    if current_song is None:
        return user_body, None, None
    song_row = get_song_memory(session, current_song.id)
    song_body = song_row.body if song_row else ""
    album_row = get_album_memory(session, current_song.album_id)
    album_body = album_row.body if album_row and album_row.body else None
    return user_body, song_body, album_body


def _unique_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _format_version(version, song: Song) -> str:
    parts = [
        f"id: {version.id}",
        f"song_id: {song.id}",
        f"song_title: {song.title}",
        f"version_number: {version.version_number}",
    ]
    if version.prompt:
        parts.append(f"style: {version.prompt}")
    if version.key_scale:
        parts.append(f"key: {version.key_scale}")
    if version.bpm:
        parts.append(f"bpm: {version.bpm}")
    if version.audio_duration:
        parts.append(f"duration: {version.audio_duration}s")
    if version.lyrics:
        parts.append(f"lyrics:\n{version.lyrics}")
    return "\n".join(parts)


def resolve_mention_blocks(
    session: Session,
    user: AuthenticatedUser,
    current_song: Song | None,
    mentioned_song_ids: list[str],
    mentioned_version_ids: list[str],
    mentioned_album_id: str | None,
) -> list[TurnContextBlock]:
    """Load picker-selected mention targets from the DB.

    Unknown, foreign, or unrelated IDs 404 the whole turn. The client
    never supplies lyrics or other raw context as the source of truth.
    """
    blocks = _mentioned_song_blocks(session, user, current_song, mentioned_song_ids)
    album_block = _mentioned_album_block(session, user, current_song, mentioned_album_id)
    version_block = _mentioned_version_block(session, current_song, mentioned_version_ids)
    return [block for block in (*blocks, album_block, version_block) if block is not None]


def _mentioned_song_blocks(
    session: Session,
    user: AuthenticatedUser,
    current_song: Song | None,
    mentioned_song_ids: list[str],
) -> list[TurnContextBlock]:
    current_id = current_song.id if current_song is not None else None
    songs = [
        check_song_access(session, song_id, user)
        for song_id in _unique_ids(mentioned_song_ids)
        if song_id != current_id
    ]
    if not songs:
        return []
    body = "\n\n".join(_format_current_song(song) for song in songs)
    return [TurnContextBlock(TURN_BLOCK_MENTIONED_SONGS, body)]


def _mentioned_album_block(
    session: Session,
    user: AuthenticatedUser,
    current_song: Song | None,
    mentioned_album_id: str | None,
) -> TurnContextBlock | None:
    if mentioned_album_id is None:
        return None
    if current_song is None or mentioned_album_id != current_song.album_id:
        raise HTTPException(404, "Album not found")
    album = get_album(session, mentioned_album_id)
    check_album_access(album, user)
    tracks = list_songs(
        session,
        album_id=album.id,
        user_id=owner_filter(user),
        light=True,
    )
    body = f"id: {album.id}\ntitle: {album.title}\ntracks:\n"
    return TurnContextBlock(
        TURN_BLOCK_MENTIONED_ALBUM,
        body + "\n\n".join(_format_current_song(song) for song in tracks),
    )


def _mentioned_version_block(
    session: Session,
    current_song: Song | None,
    mentioned_version_ids: list[str],
) -> TurnContextBlock | None:
    version_ids = _unique_ids(mentioned_version_ids)
    if not version_ids:
        return None
    if current_song is None:
        raise HTTPException(404, "Version not found")
    versions = [get_version(session, version_id, current_song.id) for version_id in version_ids]
    if any(version is None for version in versions):
        raise HTTPException(404, "Version not found")
    body = "\n\n".join(_format_version(version, current_song) for version in versions)
    return TurnContextBlock(TURN_BLOCK_MENTIONED_VERSIONS, body)


def _generation_is_playable(generation: Generation) -> bool:
    return (not generation.is_archived) and bool(generation.mp3_path)


def _format_take(generation: Generation) -> str:
    whisper = generation.whisper_text or ""
    parts = [
        f"generation_id: {generation.id}",
        f"generation_number: {generation.generation_number}",
        f"whisper_text:\n{whisper}",
        f"is_picked: {str(generation.is_picked).lower()}",
        f"is_kept: {str(generation.is_kept).lower()}",
    ]
    score_lines = [
        f"{key}: {value}" for key, value in sorted(score_values(generation).items())
    ]
    if score_lines:
        parts.append("scores:\n" + "\n".join(score_lines))
    return "\n".join(parts)


def resolve_take_block(
    session: Session,
    user: AuthenticatedUser,
    current_song: Song | None,
    current_generation_id: str | None,
) -> TurnContextBlock | None:
    """Pick the relevant playable take for the open song.

    An explicit player id is used only when it is owned, belongs to the
    current song, and is playable. Otherwise the server falls back to the
    playable pick, then the newest playable take. Missing takes are a
    named empty state, never a silent substitute.
    """
    if current_generation_id is not None:
        generation = check_generation_access(session, current_generation_id, user)
        if current_song is None or generation.song_id != current_song.id:
            raise HTTPException(
                422,
                "Generation does not belong to the current song",
            )
        if not _generation_is_playable(generation):
            raise HTTPException(422, "Generation is not playable")
        return TurnContextBlock(TURN_BLOCK_CURRENT_TAKE, _format_take(generation))

    if current_song is None:
        return None
    playable = best_playable_generation(current_song)
    if playable is None:
        return TurnContextBlock(TURN_BLOCK_NO_TAKE, "no playable take")
    return TurnContextBlock(TURN_BLOCK_CURRENT_TAKE, _format_take(playable))


# ── Chat turn ─────────────────────────────────────────────────────────


SSE_MEDIA_TYPE = "text/event-stream"


@dataclass(frozen=True)
class PreparedChatTurn:
    messages: list[TurnMessage]
    windowed: bool
    tail_budget: int
    job_id: str
    conversation_id: str
    user_message: ChatMessageResponse


@dataclass
class ChatTurnLifecycle:
    session: Session
    job_id: str
    heartbeat_task: asyncio.Task[None]

    async def finish(self, *, cancelled: bool) -> None:
        from songmaker_cli.jobs._runtime import (
            _cancel_chat_job,
            _stop_chat_job_heartbeat,
        )

        if cancelled:
            await _cancel_chat_job(self.session, self.heartbeat_task, self.job_id)
            return
        await _stop_chat_job_heartbeat(self.heartbeat_task, self.job_id)


class ChatTurnFrames:
    """Relay one running turn's SSE frames to its client for as long as it listens.

    A client that leaves ends the relay, never the turn: the turn runs to
    completion and persists its reply for the panel that returns (#1014).
    """

    def __init__(self) -> None:
        self._pending: asyncio.Queue[str | None] = asyncio.Queue()
        self._listening = True

    def publish(self, frame: str) -> None:
        if self._listening:
            self._pending.put_nowait(frame)

    def end(self) -> None:
        self._pending.put_nowait(None)

    async def relay(self) -> AsyncIterator[str]:
        try:
            while (frame := await self._pending.get()) is not None:
                yield frame
        finally:
            self._listening = False


_running_chat_turns: set[asyncio.Task[None]] = set()


def fail_chat_turns_ended_by_restart(db_factory: sessionmaker[Session]) -> None:
    """At web-process startup, fail every chat job a previous process left active.

    A turn runs only as a task of the web process that started it, so none
    survives a restart. Failing its job at once lets the returning panel show
    the unanswered message with Try again and accept a new one, instead of
    following a turn that no longer runs until the stale-job reaper notices
    (#1014).
    """
    with db_factory() as session:
        recover_stale_jobs_by_type(session, {JobType.CHAT: JOB_ACTIVE_STATUSES})
        session.commit()


def _start_chat_turn(
    req: ChatTurnV2Request, caller: TurnCaller, prepared: PreparedChatTurn,
) -> ChatTurnFrames:
    frames = ChatTurnFrames()
    turn = asyncio.create_task(_run_chat_turn(req, caller, prepared, frames))
    _running_chat_turns.add(turn)
    turn.add_done_callback(_forget_chat_turn)
    return frames


def _forget_chat_turn(turn: asyncio.Task[None]) -> None:
    _running_chat_turns.discard(turn)
    if not turn.cancelled() and (crash := turn.exception()) is not None:
        log.error("Co-writer turn ended with an error", exc_info=crash)


async def _run_chat_turn(
    req: ChatTurnV2Request,
    caller: TurnCaller,
    prepared: PreparedChatTurn,
    frames: ChatTurnFrames,
) -> None:
    """Run a started turn on its own session, independent of the request that started it."""
    from songmaker_cli.jobs._runtime import _keep_chat_job_heartbeat

    db_factory: sessionmaker[Session] = caller.app.state.ctx.db
    try:
        with db_factory() as session:
            lifecycle = ChatTurnLifecycle(
                session,
                prepared.job_id,
                asyncio.create_task(_keep_chat_job_heartbeat(db_factory, prepared.job_id)),
            )
            async for frame in _chat_event_generator(req, caller, session, prepared, lifecycle):
                frames.publish(frame)
    finally:
        frames.end()


_PROBLEM_STATUS: Final = {
    ChatTurnProblem.UNAVAILABLE: 503,
    ChatTurnProblem.BUSY: 429,
    ChatTurnProblem.NOT_ENABLED: 403,
    ChatTurnProblem.SIGN_IN_AGAIN: 401,
}
_TURN_FAILED_STATUS: Final = 500
_TURN_ALREADY_RUNNING_STATUS: Final = 409
_CHAT_REQUEST_FAILED: Final = "Chat request failed"
_CHAT_COMPLETION_FAILED: Final = "Chat completion failed"


def _sse_format(event: BaseModel) -> str:
    return f"data: {json.dumps(event.model_dump())}\n\n"


@router.post(
    "/chat/turn",
    responses={
        404: {"description": "Mentioned album or version does not exist"},
        409: {"description": "Another co-writer turn is still running"},
        422: {"description": "Chat context or co-writer configuration is invalid"},
    },
)
async def api_chat_turn(
    req: ChatTurnV2Request,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StreamingResponse:
    prepared = _prepare_chat_turn(req, request, user, session)
    session_id = session_id_from_request(request, installed_web_auth_config(request.app))
    frames = _start_chat_turn(req, TurnCaller(request.app, session_id, user), prepared)
    return StreamingResponse(
        frames.relay(),
        media_type=SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _prepare_chat_turn(
    req: ChatTurnV2Request,
    request: Request,
    user: AuthenticatedUser,
    session: Session,
) -> PreparedChatTurn:
    envelope = _chat_turn_context(req, user, session)
    job = create_job_with_rate_limit(
        session,
        user,
        JobType.CHAT,
        redis=request.app.state.ctx.redis,
    )
    _refuse_while_another_turn_runs(session, user)
    update_job_status(session, job.id, JobStatusUpdate(JobStatus.RUNNING))
    session.commit()
    return _prepare_chat_messages(req, user, session, envelope, job.id)


def _refuse_while_another_turn_runs(session: Session, user: AuthenticatedUser) -> None:
    """Refuse a turn while another one runs, so no message is ever answered twice.

    Runs once the new turn's own chat job exists, before the commit that
    releases the rate-limit lock, so two turns sent at once cannot both pass;
    the panel that is refused follows the running turn instead (#1014).
    """
    if _running_turn_count(session, user) > 1:
        session.rollback()
        raise HTTPException(
            _TURN_ALREADY_RUNNING_STATUS,
            "A co-writer reply is still being written",
        )


def _chat_turn_context(
    req: ChatTurnV2Request,
    user: AuthenticatedUser,
    session: Session,
) -> TurnContextEnvelope:
    current_song = (
        check_song_access(session, req.current_song_id, user)
        if req.current_song_id is not None
        else None
    )
    extra_blocks = resolve_mention_blocks(
        session,
        user,
        current_song,
        req.mentioned_song_ids,
        req.mentioned_version_ids,
        req.mentioned_album_id,
    )
    if take_block := resolve_take_block(session, user, current_song, req.current_generation_id):
        extra_blocks.append(take_block)
    user_memory_body, song_memory_body, album_notes_body = load_memory_for_turn(
        session,
        user.id,
        current_song,
    )
    return compose_turn_context(
        current_song=current_song,
        user_memory_body=user_memory_body,
        song_memory_body=song_memory_body,
        album_notes_body=album_notes_body,
        extra_blocks=extra_blocks,
    )


def _prepare_chat_messages(
    req: ChatTurnV2Request,
    user: AuthenticatedUser,
    session: Session,
    envelope: TurnContextEnvelope,
    job_id: str,
) -> PreparedChatTurn:
    from songmaker_cli.jobs._runtime import _fail_chat_job

    try:
        conversation = get_or_create_active_conversation(session, user.id)
        history = list_messages(session, conversation.id)
        retried = _unanswered_message_sent_again(history, req.message)
        if retried is not None:
            history = history[:-1]
        tail_budget = get_cowriter_tail_token_budget(session)
        compacted = compact_conversation(
            history,
            budget=tail_budget,
            existing=conversation.summary,
            summarize=fold_summary,
        )
        _save_compacted_summary(session, conversation, history, compacted)
        messages = [
            TurnMessage(role=message["role"], text=message["content"])
            for message in compacted.to_api_messages()
        ]
        messages.append(TurnMessage(role="user", text=envelope.wrap_user_message(req.message)))
        user_message = retried or append_message(
            session,
            conversation.id,
            "user",
            req.message,
            song_id=req.current_song_id,
        )
        session.commit()
    except asyncio.CancelledError:
        _fail_chat_job(session, job_id, "Chat request cancelled", "cancelled")
        raise
    except Exception:
        log.exception("Co-writer chat setup failed")
        _fail_chat_job(session, job_id, "Chat setup failed", "setup_error")
        raise
    return PreparedChatTurn(
        messages,
        compacted.windowed,
        tail_budget,
        job_id,
        conversation.id,
        ChatMessageResponse.from_orm(user_message),
    )


def _unanswered_message_sent_again(
    history: Sequence[ChatMessage],
    message: str,
) -> ChatMessage | None:
    """Return the conversation's unanswered last message when this turn sends it again.

    A turn that ends without a reply keeps the message it was started with,
    and Try again resends that text; the new turn answers the retained
    message instead of repeating it (#1014). No other turn can still be
    answering it: a turn only starts while none runs.
    """
    last = history[-1] if history else None
    if last is not None and last.role == "user" and last.content == message:
        return last
    return None


def _save_compacted_summary(session: Session, conversation, history, compacted) -> None:
    if not compacted.windowed or compacted.summary_text is None:
        return
    upsert_summary(
        session,
        conversation.id,
        compacted.summary_text,
        compacted.last_summarized_message_id,
        message_count=len(history),
        token_count=(
            count_tokens(compacted.summary_text)
            + sum(count_tokens(msg.content) for msg in compacted.tail)
        ),
    )
    session.commit()


async def _chat_event_generator(
    req: ChatTurnV2Request,
    caller: TurnCaller,
    session: Session,
    prepared: PreparedChatTurn,
    lifecycle: ChatTurnLifecycle,
) -> AsyncIterator[str]:
    """Stream one turn's frames; whatever happens, even opening the stream, finishes its job."""
    started = time.monotonic()
    terminal = False
    try:
        stream = run_cowriter_turn(caller, prepared.messages)
        try:
            assistant_text = ""
            problem: TurnProblem | None = None
            try:
                async for outcome in stream:
                    if isinstance(outcome, TurnProblem):
                        problem = outcome
                        break
                    if isinstance(outcome, TurnAnswer):
                        assistant_text = outcome.text
                        break
                    yield _sse_format(outcome)
                await stream.aclose()
            except Exception as exc:
                terminal = True
                yield _chat_failure_event(session, prepared.job_id, exc)
                return
            if problem is not None:
                terminal = True
                yield _turn_problem_event(session, prepared.job_id, problem)
                return
            _log_chat_turn(prepared, started)
            try:
                final_event = _complete_chat_turn(req, session, prepared, assistant_text)
            except Exception:
                terminal = True
                yield _chat_completion_failure_event(session, prepared.job_id)
                return
            terminal = True
            yield _sse_format(final_event)
        finally:
            await stream.aclose()
    finally:
        await lifecycle.finish(cancelled=not terminal)


def _log_chat_turn(prepared: PreparedChatTurn, started: float) -> None:
    log.info(
        "cowriter turn windowed=%s duration_ms=%d tail_budget=%d",
        prepared.windowed,
        int((time.monotonic() - started) * 1000),
        prepared.tail_budget,
    )


def _turn_problem_event(session: Session, job_id: str, turn_problem: TurnProblem) -> str:
    from songmaker_cli.jobs._runtime import _fail_chat_job

    problem = turn_problem.problem
    log.warning("Co-writer turn did not run (%s): %s", problem.value, turn_problem.detail)
    _fail_chat_job(session, job_id, f"{problem.value}: {turn_problem.detail}", problem.value)
    return _sse_format(
        ChatTurnProblemFrame(
            status=_PROBLEM_STATUS[problem],
            problem=problem,
            retry_after_seconds=turn_problem.retry_after_seconds,
        ),
    )


def _chat_failure_event(session: Session, job_id: str, exc: Exception) -> str:
    from songmaker_cli.jobs._runtime import _fail_chat_job

    log.error("Co-writer chat failed (%s)", type(exc).__name__)
    _fail_chat_job(session, job_id, _CHAT_REQUEST_FAILED, "chat_error")
    return _sse_format(
        ChatTurnFailureFrame(status=_TURN_FAILED_STATUS, message=_CHAT_REQUEST_FAILED),
    )


def _complete_chat_turn(
    req: ChatTurnV2Request,
    session: Session,
    prepared: PreparedChatTurn,
    assistant_text: str,
) -> ChatTurnFinalFrame:
    assistant_message = append_message(
        session,
        prepared.conversation_id,
        "assistant",
        assistant_text,
        song_id=req.current_song_id,
    )
    if not update_job_status(
        session, prepared.job_id, JobStatusUpdate(JobStatus.COMPLETED, progress=1.0),
    ):
        log.warning("Chat job %s was already terminal at completion", prepared.job_id)
    session.commit()
    return ChatTurnFinalFrame(
        conversation_id=prepared.conversation_id,
        user_message=prepared.user_message,
        assistant_message=ChatMessageResponse.from_orm(assistant_message),
    )


def _chat_completion_failure_event(session: Session, job_id: str) -> str:
    from songmaker_cli.jobs._runtime import _fail_chat_job

    log.exception("Co-writer chat completion failed")
    _fail_chat_job(session, job_id, _CHAT_COMPLETION_FAILED, "completion_error")
    return _sse_format(
        ChatTurnFailureFrame(status=_TURN_FAILED_STATUS, message=_CHAT_COMPLETION_FAILED),
    )


# ── Conversation CRUD ────────────────────────────────────────────────


def _verify_owns_conversation(
    session: Session,
    conversation_id: str,
    user: AuthenticatedUser,
):
    conv = get_conversation(session, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.get("/conversations")
def api_list_conversations(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ConversationListResponse:
    rows = recent_conversations(session, user.id)
    return ConversationListResponse(
        conversations=[ConversationResponse.from_row(r) for r in rows],
    )


@router.get(
    "/conversations/{conversation_id}",
    responses={404: {"description": "Conversation does not exist"}},
)
def api_conversation_messages(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ConversationMessagesResponse:
    conv = _verify_owns_conversation(session, conversation_id, user)
    messages = list_messages(session, conversation_id)
    return ConversationMessagesResponse(
        conversation_id=conv.id,
        title=conv.title,
        archived_at=conv.archived_at.isoformat() if conv.archived_at else None,
        messages=[ChatMessageResponse.from_orm(m) for m in messages],
        turn_running=_turn_running(session, conv, user),
    )


def _turn_running(session: Session, conversation: Conversation, user: AuthenticatedUser) -> bool:
    """A turn runs only in the active conversation, and only while its chat job is active."""
    return conversation.archived_at is None and _running_turn_count(session, user) > 0


def _running_turn_count(session: Session, user: AuthenticatedUser) -> int:
    """Each running co-writer turn holds an active chat job.

    A web-process restart fails the jobs its turns held; the stale-job reaper
    ends any other whose heartbeat stopped.
    """
    return count_user_active_jobs(session, user.id, JobType.CHAT)


@router.post("/conversations/new")
def api_new_conversation(
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> ConversationResponse:
    active = get_active_conversation(session, user.id)
    if active is not None:
        archive_conversation(session, active.id)
    new_conv = create_conversation(session, user.id)
    session.commit()
    return ConversationResponse.from_orm(new_conv)


@router.delete(
    "/conversations/{conversation_id}",
    responses={404: {"description": "Conversation does not exist"}},
)
def api_delete_conversation(
    conversation_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> StatusResponse:
    _verify_owns_conversation(session, conversation_id, user)
    delete_conversation(session, conversation_id)
    session.commit()
    return StatusResponse()


# ── Memory ────────────────────────────────────────────────────────


@router.get("/memory")
def api_get_memory(
    song_id: str | None = None,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MemoryBundleResponse:
    user_row = get_user_memory(session, user.id)
    bundle = MemoryBundleResponse(
        user=MemoryScopeResponse.from_orm(MEMORY_SCOPE_USER, user.id, user_row),
    )
    if song_id is None:
        return bundle
    song = check_song_access(session, song_id, user)
    song_row = get_song_memory(session, song.id)
    album_row = get_album_memory(session, song.album_id)
    return MemoryBundleResponse(
        user=bundle.user,
        song=MemoryScopeResponse.from_orm(MEMORY_SCOPE_SONG, song.id, song_row),
        album=MemoryScopeResponse.from_orm(
            MEMORY_SCOPE_ALBUM,
            song.album_id,
            album_row,
        ),
    )


@router.put("/memory/user")
def api_put_user_memory(
    req: MemoryUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MemoryScopeResponse:
    row = upsert_user_memory(session, user.id, req.body)
    session.commit()
    return MemoryScopeResponse.from_orm(MEMORY_SCOPE_USER, user.id, row)


@router.put("/memory/songs/{song_id}")
def api_put_song_memory(
    song_id: str,
    req: MemoryUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MemoryScopeResponse:
    check_song_access(session, song_id, user)
    row = upsert_song_memory(session, song_id, req.body)
    session.commit()
    return MemoryScopeResponse.from_orm(MEMORY_SCOPE_SONG, song_id, row)


@router.put("/memory/albums/{album_id}")
def api_put_album_memory(
    album_id: str,
    req: MemoryUpdateRequest,
    user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_db_session),
) -> MemoryScopeResponse:
    album = get_album(session, album_id)
    check_album_access(album, user)
    row = upsert_album_memory(session, album_id, req.body)
    session.commit()
    return MemoryScopeResponse.from_orm(MEMORY_SCOPE_ALBUM, album_id, row)
