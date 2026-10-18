"""Cover image capability and saved-route dispatch."""

from pathlib import Path

import pytest
from agent_providers import dispatch
from agent_providers.catalog import ProviderRoute
from agent_providers.errors import ProviderUnavailableError, SafeRouteReasonCode
from agent_providers.process import AgentCliUnavailableError

from songmaker_cli.cover_job_errors import CoverImageToolUnavailableError
from songmaker_cli.cowriter import routing
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.queries.settings import set_cover_settings


def _mount_a_signed_in_codex_cli(monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "codex_cover_image_capability_is_available", lambda: True)
    monkeypatch.setattr(dispatch, "codex_cli_access_token_is_present", lambda: True)


def _cover_session(tmp_path: Path, provider: str, route: str, model: str):
    factory = init_test_db(tmp_path / "cover-dispatch.db")
    session = factory()
    set_cover_settings(session, provider, route, model)
    session.commit()
    return session


@pytest.mark.parametrize(
    ("provider", "route", "expected_code"),
    [
        ("codex", ProviderRoute.CLI, None),
        ("codex", ProviderRoute.API, SafeRouteReasonCode.NO_IMAGE_TOOL),
        ("claude", ProviderRoute.CLI, SafeRouteReasonCode.NO_IMAGE_TOOL),
        ("claude", ProviderRoute.API, SafeRouteReasonCode.NO_IMAGE_TOOL),
        ("grok", ProviderRoute.CLI, SafeRouteReasonCode.NO_IMAGE_TOOL),
        ("grok", ProviderRoute.API, SafeRouteReasonCode.NO_IMAGE_TOOL),
    ],
)
def test_only_the_codex_cli_route_owns_an_image_tool(
    monkeypatch, provider: str, route: ProviderRoute, expected_code,
) -> None:
    """1346-F14-cover: preserve cover capability, selection and failure outcomes."""
    _mount_a_signed_in_codex_cli(monkeypatch)

    capability = dispatch.cover_image_capability(provider, route)

    assert capability.carries_image_tool is (expected_code is None)
    failure = capability.failure
    assert (failure.code if failure is not None else None) is expected_code


def test_the_codex_cover_route_names_a_missing_cli_login(monkeypatch) -> None:
    """1346-F14-cover: preserve cover capability, selection and failure outcomes."""
    monkeypatch.setattr(dispatch, "codex_cover_image_capability_is_available", lambda: True)
    monkeypatch.setattr(dispatch, "codex_cli_access_token_is_present", lambda: False)

    capability = dispatch.cover_image_capability("codex", ProviderRoute.CLI)

    assert capability.carries_image_tool is True
    assert capability.failure.code is SafeRouteReasonCode.CLI_LOGIN_NOT_CONFIGURED


def test_the_codex_cover_route_names_an_unmounted_cli(monkeypatch) -> None:
    """1346-F14-cover: preserve cover capability, selection and failure outcomes."""
    monkeypatch.setattr(dispatch, "codex_cover_image_capability_is_available", lambda: False)

    capability = dispatch.cover_image_capability("codex", ProviderRoute.CLI)

    assert capability.carries_image_tool is True
    assert capability.failure.code is SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE


def test_the_saved_cover_selection_resolves_to_its_route_and_model(
    monkeypatch, tmp_path: Path,
) -> None:
    """1346-F14-cover: preserve cover capability, selection and failure outcomes."""
    _mount_a_signed_in_codex_cli(monkeypatch)
    session = _cover_session(tmp_path, "codex", "cli", "gpt-5.4")

    assert routing.cover_image_provider_method(session) == routing.CoverImageDispatch(
        provider="codex", route=ProviderRoute.CLI, model="gpt-5.4",
    )


def test_a_saved_provider_without_an_image_tool_is_named_never_swapped(tmp_path: Path) -> None:
    """1346-F14-cover: preserve cover capability, selection and failure outcomes."""
    session = _cover_session(tmp_path, "claude", "cli", "")

    with pytest.raises(CoverImageToolUnavailableError) as raised:
        routing.cover_image_provider_method(session)

    assert raised.value.provider == "claude"


def test_a_saved_route_this_build_does_not_know_is_named_not_guessed(tmp_path: Path) -> None:
    """1346-F14-cover: preserve cover capability, selection and failure outcomes."""
    session = _cover_session(tmp_path, "codex", "grpc", "")

    with pytest.raises(ProviderUnavailableError) as raised:
        routing.cover_image_provider_method(session)

    assert raised.value.route == "grpc"
    assert raised.value.reason.code is SafeRouteReasonCode.ROUTE_FAILED


def test_codex_cover_route_reports_an_unavailable_cli_probe(
    monkeypatch, tmp_path: Path,
) -> None:
    """1346-F14-cover: preserve cover capability, selection and failure outcomes."""
    monkeypatch.setattr(dispatch, "codex_cover_image_capability_is_available", lambda: True)
    monkeypatch.setattr(
        dispatch,
        "codex_cli_access_token_is_present",
        lambda: (_ for _ in ()).throw(AgentCliUnavailableError("unreadable mirror")),
    )
    session = _cover_session(tmp_path, "codex", "cli", "")

    with pytest.raises(ProviderUnavailableError) as raised:
        routing.cover_image_provider_method(session)

    assert raised.value.reason.code is SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE
