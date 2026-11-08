"""The MCP endpoint of a person's own agent: the marked routes served as tools on ``/mcp``.

A route becomes a tool only by carrying ``agent_tool`` as its ``openapi_extra``; the tool calls
that route in-process through the whole app, so every middleware and ownership check applies
to it exactly as to a browser. The gate admits the agent's token at ``/mcp`` and on the marked
routes as the person behind it, capped to the role ``user``.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

from agent_runtime_client.mcp_server import McpPersonFront, RouteTools, route_tools
from agent_runtime_client.mcp_wire import MCP_ENDPOINT_PATH
from agent_runtime_client.tools import Principal
from starlette.requests import HTTPConnection
from webauth.middleware.bearer_gate import (
    MarkedRoute,
    ProtectedResource,
    install_resource_metadata,
    resource_person,
)
from webauth.policies import AuthorizedParties

from songmaker_cli.auth_stores import DatabaseSignInTransaction
from songmaker_cli.constants import OIDC_MCP_GROUP

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import FastAPI
    from sqlalchemy.orm import Session, sessionmaker
    from starlette.types import Scope

    from songmaker_cli.oidc_client import OidcSignIn
    from songmaker_cli.settings import Settings


def collect_route_tools(app: FastAPI) -> RouteTools:
    """The tools of the app's marked routes; a mark outside the generator's profile raises.

    Call it after the last route that appears in the schema is registered: ``app.openapi()``
    caches its first result.
    """
    return route_tools(app.openapi(), app, mark_route=MarkedRoute)


def build_protected_resource(
    settings: Settings,
    marks: frozenset[MarkedRoute],
    database: sessionmaker[Session],
) -> ProtectedResource | None:
    """The resource at ``/mcp`` while the agent client and scope are configured, else none."""
    agent = settings.agent
    if (
        agent is None
        or agent.mcp_client_id is None
        or agent.mcp_scope is None
        or agent.mcp_agent_group is None
    ):
        return None
    return ProtectedResource(
        url=f"{settings.public_base_url}{MCP_ENDPOINT_PATH}",
        scope=agent.mcp_scope,
        required_group=OIDC_MCP_GROUP,
        agent_group=agent.mcp_agent_group,
        authorized_parties=AuthorizedParties(frozenset({agent.mcp_client_id})),
        transaction=DatabaseSignInTransaction(database),
        marked_routes=marks,
    )


def mount_mcp_front(
    app: FastAPI,
    tools: RouteTools,
    resource: ProtectedResource | None,
    oidc_sign_in: OidcSignIn,
) -> McpPersonFront | None:
    """Serve ``/mcp`` and the resource's metadata document; the gate admits before routing.

    Returns the front, which serves only inside ``running()``: the app's lifespan enters it.
    With no resource the endpoint is off and there is no front.
    """
    if resource is None:
        return None
    issuer = oidc_sign_in.relying_party.issuer

    def resolve_person(scope: Scope) -> Principal:
        return Principal(iss=issuer, sub=resource_person(HTTPConnection(scope)).id)

    front = McpPersonFront(tools.tools, resolve_person=resolve_person)
    app.router.add_route(MCP_ENDPOINT_PATH, front, include_in_schema=False)
    install_resource_metadata(app, resource, issuer=issuer)
    return front


@asynccontextmanager
async def running_mcp_front(app: FastAPI) -> AsyncIterator[None]:
    """Hold the app's front inside ``running()``; with the endpoint off there is nothing to run."""
    front: McpPersonFront | None = app.state.mcp_front
    async with AsyncExitStack() as stack:
        if front is not None:
            await stack.enter_async_context(front.running())
        yield
