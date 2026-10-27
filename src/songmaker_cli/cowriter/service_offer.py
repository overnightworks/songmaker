"""What the agent service offers the signed-in admin for the co-writer's model.

``read_offer`` checks in the order that spends least: the service address first (without one, no
token is fetched, so no refresh token rotates for nothing), then the admin's own tokens, then
``GET /offer``. Every outcome is one closed ``CowriterOfferState``; none of the tokens is
logged, returned or stored here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Final

import httpx
from agent_runtime_client.wire import Offer, RejectionCode, RunRejection, parse_offer
from pydantic import ValidationError

from songmaker_cli.api_models import ChatTurnProblem, CowriterOfferState
from songmaker_cli.cowriter.service_turn import (
    WORKLOAD_TOKEN_HEADER,
    TurnProblem,
    cowriter_model_id,
    fetch_tokens,
    service_client,
)
from songmaker_cli.settings import get_settings

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger(__name__)

_UNREAD_STATES: Final = frozenset(
    {CowriterOfferState.NOT_REACHABLE, CowriterOfferState.SIGN_IN_AGAIN},
)
OFFER_PATH: Final = "/offer"
# Shorter than a run's stream timeout: a page view must not wait on a service that stalls.
OFFER_TIMEOUT_SECONDS: Final = 10.0


async def read_offer(app: FastAPI, session_id: str | None) -> CowriterOfferState:
    """The state of the co-writer's model in this admin's offer."""
    state = await _state_of_the_offer(app, session_id)
    if state in _UNREAD_STATES:
        log.info("The agent service's offer is not readable: %s", state.value)
    return state


async def _state_of_the_offer(app: FastAPI, session_id: str | None) -> CowriterOfferState:
    service_url = get_settings().agent_service_url
    if not service_url:
        return CowriterOfferState.NOT_REACHABLE
    tokens = await asyncio.to_thread(fetch_tokens, app, session_id)
    if isinstance(tokens, TurnProblem):
        if tokens.problem is ChatTurnProblem.SIGN_IN_AGAIN:
            return CowriterOfferState.SIGN_IN_AGAIN
        return CowriterOfferState.NOT_REACHABLE
    try:
        async with service_client(service_url) as client:
            response = await client.get(
                OFFER_PATH,
                headers={
                    "Authorization": f"Bearer {tokens.user.get_secret_value()}",
                    WORKLOAD_TOKEN_HEADER: tokens.workload.get_secret_value(),
                },
                timeout=OFFER_TIMEOUT_SECONDS,
            )
    except httpx.HTTPError:
        return CowriterOfferState.NOT_REACHABLE
    return _state_of_the_answer(response)


def _state_of_the_answer(response: httpx.Response) -> CowriterOfferState:
    try:
        answer = parse_offer(response.content)
    except ValidationError:
        return CowriterOfferState.NOT_REACHABLE
    if isinstance(answer, RunRejection):
        forbidden = (
            response.status_code == httpx.codes.FORBIDDEN and answer.code is RejectionCode.FORBIDDEN
        )
        return CowriterOfferState.NOT_AVAILABLE if forbidden else CowriterOfferState.NOT_REACHABLE
    if response.status_code != httpx.codes.OK:
        return CowriterOfferState.NOT_REACHABLE
    return _state_of_the_entry(answer)


def _state_of_the_entry(offer: Offer) -> CowriterOfferState:
    if not offer.data:
        return CowriterOfferState.NOT_AVAILABLE
    current = cowriter_model_id()
    for entry in offer.data:
        if entry.id == current:
            return CowriterOfferState.READY if entry.ready else CowriterOfferState.NOT_BUILT
    return CowriterOfferState.NO_LONGER_OFFERED
