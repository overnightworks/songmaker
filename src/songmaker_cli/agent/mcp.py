"""The MCP endpoint of a person's own agent: the marked routes served as tools on ``/mcp``.

A route becomes a tool only by carrying ``agent_tool`` as its ``openapi_extra``; the tool calls
that route in-process through the whole app, so every middleware and ownership check applies
to it exactly as to a browser. The gate admits the agent's token at ``/mcp`` and on the marked
routes as the person behind it, capped to the role ``user``. Every other route carries
``exclude_route`` with the reason of its class, and an operation with neither stops the build.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from enum import StrEnum
from typing import TYPE_CHECKING

from agents.mcp_server import McpPersonFront, RouteTools, route_tools
from agents.mcp_wire import MCP_ENDPOINT_PATH
from agents.tools import Principal, not_an_agent_tool
from agents.tools import ToolEffect as ToolEffect
from agents.tools import agent_tool as agent_tool
from starlette.requests import HTTPConnection
from webauth.middleware.bearer_gate import (
    MarkedRoute,
    ProtectedResource,
    resource_person,
)
from webauth.policies import AuthorizedParties

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from starlette.types import Scope

    from songmaker_cli.settings import RealmSettings, Settings


class Exclusion(StrEnum):
    """Why a route is no agent tool; one wording per class, read by whoever reviews the reach."""

    ADMIN = "an agent's token never carries admin rights"
    FINAL_DELETION = "removes something for good"
    BULK_DELETION = "removes many things at once"
    SHARING = "shares the person's content with people outside their account"
    PUBLIC_VIEW = "serves a share to visitors without an account"
    BROWSER_ONLY = "a file, a stream, an upload or a notice that only the browser can use"
    NOT_A_PERSONS_ACTION = "the app's own or a monitor's call, not an action of the person"


def exclude_route(reason: Exclusion) -> dict[str, object]:
    """The route's ``openapi_extra`` when it is no tool, with the reason of its class."""
    return not_an_agent_tool(reason=reason.value)


def collect_route_tools(app: FastAPI) -> RouteTools:
    """The tools of the app's marked routes; a mark outside the generator's profile raises.

    Call it after the last route that appears in the schema is registered: ``app.openapi()``
    caches its first result.
    """
    return route_tools(app.openapi(), app, mark_route=MarkedRoute)


def build_protected_resource(
    settings: Settings,
    realm: RealmSettings,
    marks: frozenset[MarkedRoute],
) -> ProtectedResource | None:
    """The resource at ``/mcp`` while the agent client and scope are configured, else none."""
    if realm.mcp_client_id is None or realm.mcp_scope is None or realm.agent_group is None:
        return None
    return ProtectedResource(
        url=f"{settings.public_base_url}{MCP_ENDPOINT_PATH}",
        scope=realm.mcp_scope,
        required_group=realm.mcp_group,
        agent_group=realm.agent_group,
        authorized_parties=AuthorizedParties(frozenset({realm.mcp_client_id})),
        marked_routes=marks,
    )


def mount_mcp_front(
    app: FastAPI,
    tools: RouteTools,
    resource: ProtectedResource | None,
    issuer: str,
) -> McpPersonFront | None:
    """Serve ``/mcp``; the gate admits before routing, and ``auth.install`` serves the resource's
    metadata document. Call it before ``auth.install``, so ``/mcp`` is a route of the host.

    Returns the front, which serves only inside ``running()``: the app's lifespan enters it.
    With no resource the endpoint is off and there is no front.
    """
    if resource is None:
        return None

    def resolve_person(scope: Scope) -> Principal:
        return Principal(iss=issuer, sub=resource_person(HTTPConnection(scope)).id)

    front = McpPersonFront(tools.tools, resolve_person=resolve_person)
    app.router.add_route(MCP_ENDPOINT_PATH, front, include_in_schema=False)
    return front


@asynccontextmanager
async def running_mcp_front(app: FastAPI) -> AsyncIterator[None]:
    """Hold the app's front inside ``running()``; with the endpoint off there is nothing to run."""
    front: McpPersonFront | None = app.state.mcp_front
    async with AsyncExitStack() as stack:
        if front is not None:
            await stack.enter_async_context(front.running())
        yield
