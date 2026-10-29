"""Presets and global generation defaults refuse the reference field, which only a version links."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PRESETS = "/api/settings/presets"
DEFAULTS = "/api/settings/generation-defaults"

REFERENCE_VALUES = ["u1/refs/a.wav", "", None]


@pytest.mark.parametrize("reference", REFERENCE_VALUES)
def test_a_preset_or_default_carrying_the_reference_field_is_refused(
    admin_client: TestClient, reference: str | None,
) -> None:
    params = {"reference_audio_path": reference}
    preset = admin_client.post(
        PRESETS, json={"name": "p", "model_mode": "sft", "params": {"inference_steps": 8}},
    ).json()

    refused = [
        admin_client.post(PRESETS, json={"name": "q", "model_mode": "sft", "params": params}),
        admin_client.put(f"{PRESETS}/{preset['id']}", json={"params": params}),
        admin_client.put(DEFAULTS, json={"sft": params}),
    ]

    assert [response.status_code for response in refused] == [422, 422, 422]
    assert [item["id"] for item in admin_client.get(PRESETS).json()] == [preset["id"]]
