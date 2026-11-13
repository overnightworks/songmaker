"""Conversation + new-flow chat endpoints (co-writer redesign).

This module owns the Phase 3 conversation-scoped chat API:

- ``POST /chat/turn`` — one turn in the user's active conversation, run through the gateway backend.
- ``GET /conversations`` — list all the user's conversations.
- ``GET /conversations/{id}`` — full message history of one.
- ``POST /conversations/new`` — archive the active one and start fresh.
- ``DELETE /conversations/{id}`` — wipe a conversation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Final

from agents.turn import TurnMessage
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker
from webauth.config import installed_web_auth_config
from webauth.dependencies import session_id_from_request
from webauth.ports import AuthenticatedUser

from songmaker_cli.agent.backend import TurnAnswer, TurnCaller, TurnProblem, run_cowriter_turn
from songmaker_cli.agent.mcp import Exclusion, ToolEffect, agent_tool, exclude_route
from songmaker_cli.agent.tools import CallingTurn, bound_to_turn
from songmaker_cli.api_helpers import (
    create_job_with_rate_limit,
)
from songmaker_cli.api_models import (
    AgentProblem,
    ChatMessageResponse,
    ChatTurnFailureFrame,
    ChatTurnFinalFrame,
    ChatTurnProblemFrame,
    ChatTurnV2Request,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationResponse,
    StatusResponse,
)
from songmaker_cli.app_context import get_db_session
from songmaker_cli.auth_dependencies import get_current_user
from songmaker_cli.cowriter.history import compact_conversation, count_tokens, fold_summary
from songmaker_cli.cowriter.turn_context import TurnContextEnvelope, load_turn_context
from songmaker_cli.db.models import ChatMessage
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
    lock_active_job,
    recover_stale_jobs_by_type,
    update_job_status,
)
from songmaker_cli.db.queries.settings import get_cowriter_tail_token_budget
from songmaker_cli.job_types import JOB_ACTIVE_STATUSES, JobStatus, JobType
from songmaker_cli.refusals import Refusal

log = logging.getLogger(__name__)

router = APIRouter()


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
        with bound_to_turn(CallingTurn(caller.session_id)), db_factory() as session:
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
    AgentProblem.UNAVAILABLE: 503,
    AgentProblem.BUSY: 429,
    AgentProblem.BUDGET_SPENT: 429,
    AgentProblem.NOT_ENABLED: 403,
    AgentProblem.SIGN_IN_AGAIN: 401,
}
_TURN_FAILED_STATUS: Final = 500
_CHAT_REQUEST_FAILED: Final = "Chat request failed"
_CHAT_COMPLETION_FAILED: Final = "Chat completion failed"


def _sse_format(event: BaseModel) -> str:
    return f"data: {json.dumps(event.model_dump())}\n\n"


@router.post(
    "/chat/turn",
    responses={
        403: {"description": "The co-writer needs a browser login"},
        404: {
            "description": "A mentioned album, version, song or take, or the current song, "
            "does not exist",
        },
        409: {"description": "Another co-writer turn is still running"},
        422: {"description": "Chat context or co-writer configuration is invalid"},
    },
    openapi_extra=exclude_route(Exclusion.BROWSER_ONLY),
)
async def api_chat_turn(
    req: ChatTurnV2Request, request: Request,
    user: AuthenticatedUser = Depends(get_current_user), session: Session = Depends(get_db_session),
) -> StreamingResponse:
    session_id = session_id_from_request(request, installed_web_auth_config(request.app))
    if session_id is None:
        raise Refusal(403, "cowriterRefusal.browserLogin")
    prepared = _prepare_chat_turn(req, request, user, session)
    frames = _start_chat_turn(req, TurnCaller(request.app, session_id, user), prepared)
    return StreamingResponse(
        frames.relay(), media_type=SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _prepare_chat_turn(
    req: ChatTurnV2Request,
    request: Request,
    user: AuthenticatedUser,
    session: Session,
) -> PreparedChatTurn:
    envelope = load_turn_context(req, user, session)
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
        raise Refusal(409, "cowriterRefusal.turnRunning")


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
                log.exception("Co-writer chat completion failed")
                yield _fail_turn_event(
                    session, prepared.job_id, _CHAT_COMPLETION_FAILED, "completion_error",
                )
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
    log.error("Co-writer chat failed (%s)", type(exc).__name__)
    return _fail_turn_event(session, job_id, _CHAT_REQUEST_FAILED, "chat_error")


def _fail_turn_event(session: Session, job_id: str, message: str, error_type: str) -> str:
    from songmaker_cli.jobs._runtime import _fail_chat_job

    _fail_chat_job(session, job_id, message, error_type)
    return _sse_format(ChatTurnFailureFrame(status=_TURN_FAILED_STATUS, message=message))


def _complete_chat_turn(
    req: ChatTurnV2Request,
    session: Session,
    prepared: PreparedChatTurn,
    assistant_text: str,
) -> ChatTurnFinalFrame | ChatTurnFailureFrame:
    # Locked before the append: a job the reaper failed must not answer a re-sent message twice.
    if lock_active_job(session, prepared.job_id) is None:
        session.rollback()
        log.warning("Chat job %s was already terminal at completion", prepared.job_id)
        return ChatTurnFailureFrame(status=_TURN_FAILED_STATUS, message="Reply came too late")
    assistant_message = append_message(
        session,
        prepared.conversation_id,
        "assistant",
        assistant_text,
        song_id=req.current_song_id,
    )
    update_job_status(session, prepared.job_id, JobStatusUpdate(JobStatus.COMPLETED, progress=1.0))
    session.commit()
    return ChatTurnFinalFrame(
        conversation_id=prepared.conversation_id,
        user_message=prepared.user_message,
        assistant_message=ChatMessageResponse.from_orm(assistant_message),
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


_LIST_CONVERSATIONS_DESCRIPTION = (
    "Lists the person's recent co-writer conversations, most recently active first, with "
    "the title and whether each is archived. Only the person's own conversations come back."
)
_GET_CONVERSATION_DESCRIPTION = (
    "Reads one of the person's own co-writer conversations: its title, whether it is "
    "archived, whether a turn is running now and every message. Another person's "
    "conversation id is not found."
)
_START_CONVERSATION_DESCRIPTION = (
    "Starts a new co-writer conversation for the person and archives their active one. "
    "The archived conversation stays readable; the co-writer continues in the new one."
)


@router.get(
    "/conversations",
    description=_LIST_CONVERSATIONS_DESCRIPTION,
    openapi_extra=agent_tool(name="list_conversations", effect=ToolEffect.READ_ONLY),
)
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
    description=_GET_CONVERSATION_DESCRIPTION,
    responses={404: {"description": "Conversation does not exist"}},
    openapi_extra=agent_tool(name="get_conversation", effect=ToolEffect.READ_ONLY),
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
        # A turn runs only in the active conversation, and only while its chat job is active.
        turn_running=conv.archived_at is None and _running_turn_count(session, user) > 0,
    )


def _running_turn_count(session: Session, user: AuthenticatedUser) -> int:
    """Each running co-writer turn holds an active chat job.

    A web-process restart fails the jobs its turns held; the stale-job reaper
    ends any other whose heartbeat stopped.
    """
    return count_user_active_jobs(session, user.id, JobType.CHAT)


@router.post(
    "/conversations/new",
    description=_START_CONVERSATION_DESCRIPTION,
    openapi_extra=agent_tool(name="start_conversation", effect=ToolEffect.SIDE_EFFECTING),
)
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
    openapi_extra=exclude_route(Exclusion.FINAL_DELETION),
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
