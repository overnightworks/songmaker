"""The public route-failure vocabulary is stable and secret-free."""

from __future__ import annotations

import pytest

from songmaker_cli.cowriter.errors import SafeRouteReasonCode, normalize_route_failure


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (SafeRouteReasonCode.API_KEY_NOT_SET, "API key is not set."),
        (SafeRouteReasonCode.CLI_LOGIN_NOT_CONFIGURED, "CLI is not signed in."),
        (SafeRouteReasonCode.CLI_AUTH_REJECTED, "CLI login was rejected or has expired."),
        (SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE, "CLI is unavailable."),
        (SafeRouteReasonCode.CLI_PROTOCOL_ERROR, "CLI returned an invalid response."),
        (SafeRouteReasonCode.API_HTTP_ERROR, "API request failed."),
        (SafeRouteReasonCode.API_PROTOCOL_ERROR, "API returned an invalid response."),
        (SafeRouteReasonCode.CATALOGUE_HTTP_ERROR, "Model catalogue request failed."),
        (SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR, "Model catalogue response was invalid."),
        (SafeRouteReasonCode.TOOL_EXECUTION_FAILED, "Co-Writer tool failed."),
        (SafeRouteReasonCode.TOOL_PROTOCOL_ERROR, "Co-Writer tool response was invalid."),
        (SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED, "Co-Writer tool-call limit was reached."),
        (
            SafeRouteReasonCode.ROUTE_TEXT_ONLY,
            "Song tools are not available over the Grok CLI today.",
        ),
        (
            SafeRouteReasonCode.CLAUDE_API_TOOL_LOOP_PENDING,
            "Claude over API needs the tool loop — coming.",
        ),
        (SafeRouteReasonCode.ROUTE_FAILED, "Selected route failed."),
    ],
)
def test_route_failure_code_has_its_exact_safe_message(code, message):
    assert normalize_route_failure(code).model_dump() == {"code": code, "message": message}
