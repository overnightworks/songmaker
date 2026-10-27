"""The judge's provider dispatch: each saved judge provider selects exactly one API adapter."""

from __future__ import annotations

from typing import Final

import pytest
from agent_providers import dispatch
from agent_providers.constants import COWRITER_GROK_CHAT_URL, COWRITER_OPENAI_CHAT_URL
from conftest import override_provider_runtime

# One distinct key per provider, so a route that reached the right adapter with someone else's
# key fails the pin instead of passing it.
_ANTHROPIC_KEY: Final = "anthropic-only-key"
_XAI_KEY: Final = "xai-only-key"
_OPENAI_KEY: Final = "openai-only-key"

# ``call_claude_once`` reads the installed configuration itself, so it is
# handed no key of its own.
_JUDGE_ROUTE_TARGETS: Final = (
    ("claude", "call_claude_once", None, None),
    ("grok", "call_openai_compatible_once", COWRITER_GROK_CHAT_URL, _XAI_KEY),
    ("codex", "call_openai_compatible_once", COWRITER_OPENAI_CHAT_URL, _OPENAI_KEY),
)


def _configure_one_key_per_provider() -> None:
    override_provider_runtime(
        anthropic_api_key=_ANTHROPIC_KEY,
        xai_api_key=_XAI_KEY,
        openai_api_key=_OPENAI_KEY,
    )


@pytest.mark.parametrize(
    ("provider", "expected_target", "expected_url", "expected_key"), _JUDGE_ROUTE_TARGETS,
)
def test_every_judge_provider_selects_exactly_one_api_adapter(
    monkeypatch,
    provider: str,
    expected_target: str,
    expected_url: str | None,
    expected_key: str | None,
) -> None:
    _configure_one_key_per_provider()
    taken: list[tuple[str, str | None, str | None]] = []

    def _record(name):
        def _call(**kwargs):
            taken.append((name, kwargs.get("api_url"), kwargs.get("api_key")))
            return "verdict"

        return _call

    for name in ("call_claude_once", "call_openai_compatible_once"):
        monkeypatch.setattr(dispatch, name, _record(name))

    assert dispatch.call_provider_once(
        provider=provider, model="model", prompt="prompt", timeout=5,
    ) == "verdict"
    assert taken == [(expected_target, expected_url, expected_key)]
