"""A voice's failure reason is answered as the agent sentence it always was and as its message."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from songmaker_cli.api_models.loras import UserLoraResponse
from songmaker_cli.constants import LoraStatus
from songmaker_cli.db.models import UserLora
from songmaker_cli.messages import Message, message


def _failed_voice(error_message: Message | None) -> UserLora:
    return UserLora(
        id="lora-1", user_id="user-1", name="Voice", slug="voice", status=LoraStatus.FAILED,
        model_mode="turbo", created_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
        error_message=error_message, samples=[],
    )


@pytest.mark.parametrize(
    ("reason", "sentence"),
    [
        pytest.param(
            message("voiceFailure.crashed"), "Training crashed or was interrupted", id="crashed",
        ),
        pytest.param(
            message("voiceFailure.modeMismatch", workerMode="'sft'", requestedMode="'turbo'"),
            "Worker completed LoRA training with model mode 'sft', expected 'turbo'",
            id="mode-mismatch",
        ),
        pytest.param(
            message("voiceFailure.recorded", cause="The worker restarted."),
            "The worker restarted.", id="recorded",
        ),
        pytest.param(None, None, id="no-reason"),
    ],
)
def test_a_failure_reason_is_answered_as_the_unchanged_agent_sentence_and_its_message(
    reason, sentence,
):
    response = UserLoraResponse.from_orm(_failed_voice(reason))

    assert response.error == sentence
    assert response.error_message == reason


def test_a_failure_reason_whose_key_the_catalog_lacks_fails_that_response_and_logs_lora_and_key(
    caplog,
):
    voice = _failed_voice(Message(key="voiceFailure.retired", values={}))

    with pytest.raises(KeyError):
        UserLoraResponse.from_orm(voice)

    assert "lora-1" in caplog.text
    assert "voiceFailure.retired" in caplog.text
