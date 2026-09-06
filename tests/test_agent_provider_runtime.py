"""Who installs the provider layer's deployment facts, and what happens without them."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from conftest import make_test_app

from agent_providers.config import (
    ProviderRuntimeAlreadyConfiguredError,
    ProviderRuntimeNotConfiguredError,
    current_config,
    reset_config,
)
from songmaker_cli.agent_runtime import configure_agent_providers
from songmaker_cli.constants import (
    CODEX_CLI_AUTH_FILE,
    CODEX_CODE_MODE_HOST_BINARY,
    CODEX_RESOURCES_DIRECTORY,
    GROK_CLI_AUTH_FILE,
)
from songmaker_cli.settings import Settings


def test_an_unconfigured_process_refuses_to_answer_for_a_provider() -> None:
    reset_config()

    with pytest.raises(ProviderRuntimeNotConfiguredError):
        current_config()


def test_resetting_drops_an_installed_configuration() -> None:
    configure_agent_providers(Settings())
    reset_config()

    with pytest.raises(ProviderRuntimeNotConfiguredError):
        current_config()


def test_songmaker_installs_its_container_mounts_and_credentials() -> None:
    reset_config()
    settings = Settings(anthropic_api_key="from-settings")

    configure_agent_providers(settings)

    config = current_config()
    assert config.claude_chat_model == settings.claude_chat_model
    assert config.anthropic_api_key.get_secret_value() == "from-settings"
    assert config.grok_cli_auth_file == Path(GROK_CLI_AUTH_FILE)
    assert config.codex_cli_auth_file == Path(CODEX_CLI_AUTH_FILE)
    assert config.codex_code_mode_host_binary == Path(CODEX_CODE_MODE_HOST_BINARY)
    assert config.codex_resources_directory == Path(CODEX_RESOURCES_DIRECTORY)
    assert config.codex_max_concurrent_processes == settings.codex_cli_max_concurrent_processes
    assert config.codex_max_concurrent_image_runs == settings.cover_max_concurrent_runs


def test_installing_the_same_deployment_facts_again_changes_nothing() -> None:
    """Every startup path a host owns may configure, in any order."""
    settings = Settings()
    configure_agent_providers(settings)
    configure_agent_providers(settings)

    assert current_config().claude_chat_model == settings.claude_chat_model


def test_installing_differing_deployment_facts_over_a_live_one_is_refused() -> None:
    configure_agent_providers(Settings())

    with pytest.raises(ProviderRuntimeAlreadyConfiguredError):
        configure_agent_providers(Settings(claude_chat_model="a-different-model"))


def test_a_configuration_is_immutable_once_installed() -> None:
    with pytest.raises(ValueError):
        current_config().claude_chat_model = "another-model"


def test_creating_the_web_application_configures_the_provider_runtime(tmp_path: Path) -> None:
    reset_config()

    make_test_app(tmp_path)

    assert current_config().claude_chat_model == Settings().claude_chat_model


def test_starting_an_arq_worker_configures_the_provider_runtime() -> None:
    """Neither worker runs the web lifespan, so each configures its own process."""
    from songmaker_cli.music_worker import MusicWorker

    worker = MusicWorker()
    worker._recover_on_startup = AsyncMock(return_value=0)
    reset_config()

    with patch("songmaker_cli.logging_config.configure_logging"):
        asyncio.run(worker.on_startup({"redis": AsyncMock()}))

    assert current_config().claude_chat_model == Settings().claude_chat_model
