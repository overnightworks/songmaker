"""Named co-writer route failures. No adapter exposes upstream error text."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class SafeRouteReasonCode(StrEnum):
    API_KEY_NOT_SET = "api_key_not_set"
    CLI_LOGIN_NOT_CONFIGURED = "cli_login_not_configured"
    CLI_AUTH_REJECTED = "cli_auth_rejected"
    CLI_BINARY_UNAVAILABLE = "cli_binary_unavailable"
    CLI_PROTOCOL_ERROR = "cli_protocol_error"
    API_HTTP_ERROR = "api_http_error"
    API_PROTOCOL_ERROR = "api_protocol_error"
    CATALOGUE_HTTP_ERROR = "catalogue_http_error"
    CATALOGUE_PROTOCOL_ERROR = "catalogue_protocol_error"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    TOOL_PROTOCOL_ERROR = "tool_protocol_error"
    TOOL_LIMIT_EXCEEDED = "tool_limit_exceeded"
    ROUTE_FAILED = "route_failed"


_SAFE_MESSAGES: dict[SafeRouteReasonCode, str] = {
    SafeRouteReasonCode.API_KEY_NOT_SET: "API key is not set.",
    SafeRouteReasonCode.CLI_LOGIN_NOT_CONFIGURED: "CLI is not signed in.",
    SafeRouteReasonCode.CLI_AUTH_REJECTED: "CLI login was rejected or has expired.",
    SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE: "CLI is unavailable.",
    SafeRouteReasonCode.CLI_PROTOCOL_ERROR: "CLI returned an invalid response.",
    SafeRouteReasonCode.API_HTTP_ERROR: "API request failed.",
    SafeRouteReasonCode.API_PROTOCOL_ERROR: "API returned an invalid response.",
    SafeRouteReasonCode.CATALOGUE_HTTP_ERROR: "Model catalogue request failed.",
    SafeRouteReasonCode.CATALOGUE_PROTOCOL_ERROR: "Model catalogue response was invalid.",
    SafeRouteReasonCode.TOOL_EXECUTION_FAILED: "Co-Writer tool failed.",
    SafeRouteReasonCode.TOOL_PROTOCOL_ERROR: "Co-Writer tool response was invalid.",
    SafeRouteReasonCode.TOOL_LIMIT_EXCEEDED: "Co-Writer tool-call limit was reached.",
    SafeRouteReasonCode.ROUTE_FAILED: "Selected route failed.",
}


class SafeRouteReason(BaseModel):
    code: SafeRouteReasonCode
    message: str


def normalize_route_failure(kind: SafeRouteReasonCode) -> SafeRouteReason:
    """Return the only public representation of a route failure."""
    return SafeRouteReason(code=kind, message=_SAFE_MESSAGES[kind])


class ProviderError(Exception):
    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(message)


class ProviderUnavailableError(ProviderError):
    def __init__(
        self,
        provider: str,
        route_or_message: str,
        reason: SafeRouteReason | None = None,
    ):
        self.route = route_or_message if reason is not None else None
        self.reason = reason
        super().__init__(provider, reason.message if reason is not None else route_or_message)


class ProviderModelCatalogUnavailableError(ProviderError):
    def __init__(
        self,
        provider: str,
        message: str,
        reason: SafeRouteReason | None = None,
    ):
        self.reason = reason
        super().__init__(provider, reason.message if reason is not None else message)
