"""The resource-stream deadline bounds the exchange and never hides an app's own errors."""

import asyncio

import pytest

from songmaker_cli.constants import RESOURCE_EVENT_STREAM_PATH
from songmaker_cli.middleware.resource_stream_deadline import ResourceStreamDeadlineMiddleware


def test_a_timeout_error_the_stream_app_raised_itself_propagates():
    async def failing_app(scope, receive, send):
        raise TimeoutError("upstream gave up")

    middleware = ResourceStreamDeadlineMiddleware(failing_app, deadline_seconds=60)
    scope = {"type": "http", "path": RESOURCE_EVENT_STREAM_PATH}

    exchange = middleware(scope, None, None)

    with pytest.raises(TimeoutError, match="upstream gave up"):
        asyncio.run(exchange)
