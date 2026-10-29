"""Presets and global generation defaults refuse a non-empty reference upload."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

PRESETS = "/api/settings/presets"
DEFAULTS = "/api/settings/generation-defaults"

REFUSED_REFERENCES = ["u1/refs/a.wav", "x", " "]
ACCEPTED_PARAMS = [
    pytest.param({"reference_audio_path": ""}, id="empty-string"),
    pytest.param({"reference_audio_path": None}, id="null"),
    pytest.param({"inference_steps": 8}, id="absent-key"),
]


def _create_preset(client: TestClient, params: dict) -> httpx.Response:
    return client.post(PRESETS, json={"name": "p", "model_mode": "sft", "params": params})


@pytest.mark.parametrize("reference", REFUSED_REFERENCES)
def test_create_preset_naming_a_reference_is_refused_and_stores_nothing(
    admin_client: TestClient,
    reference: str,
) -> None:
    response = _create_preset(admin_client, {"reference_audio_path": reference})

    assert response.status_code == 422
    assert admin_client.get(PRESETS).json() == []


@pytest.mark.parametrize("params", ACCEPTED_PARAMS)
def test_create_preset_without_a_reference_is_accepted(
    admin_client: TestClient, params: dict
) -> None:
    response = _create_preset(admin_client, params)

    assert response.status_code == 200
    assert [preset["id"] for preset in admin_client.get(PRESETS).json()] == [response.json()["id"]]


@pytest.mark.parametrize("reference", REFUSED_REFERENCES)
def test_update_preset_naming_a_reference_is_refused_and_keeps_the_stored_params(
    admin_client: TestClient,
    reference: str,
) -> None:
    preset = _create_preset(admin_client, {"inference_steps": 8}).json()

    response = admin_client.put(
        f"{PRESETS}/{preset['id']}",
        json={"params": {"reference_audio_path": reference}},
    )

    assert response.status_code == 422
    stored = next(item for item in admin_client.get(PRESETS).json() if item["id"] == preset["id"])
    assert stored["params"] == preset["params"]


@pytest.mark.parametrize(
    ("update", "expected_change"),
    [
        pytest.param({"name": "renamed"}, {"name": "renamed"}, id="name-only"),
        pytest.param({"is_default": True}, {"is_default": True}, id="is-default-only"),
        pytest.param({"params": None}, {}, id="null-params"),
        pytest.param(
            {"params": {"inference_steps": 9}},
            {"inference_steps": 9},
            id="params-without-key",
        ),
        pytest.param(
            {"params": {"inference_steps": 9, "reference_audio_path": ""}},
            {"inference_steps": 9},
            id="empty-reference",
        ),
        pytest.param(
            {"params": {"inference_steps": 9, "reference_audio_path": None}},
            {"inference_steps": 9},
            id="null-reference",
        ),
    ],
)
def test_update_preset_without_a_reference_is_stored(
    admin_client: TestClient, update: dict, expected_change: dict
) -> None:
    preset = _create_preset(admin_client, {"inference_steps": 8}).json()

    response = admin_client.put(f"{PRESETS}/{preset['id']}", json=update)

    assert response.status_code == 200
    stored = next(item for item in admin_client.get(PRESETS).json() if item["id"] == preset["id"])
    assert stored["name"] == expected_change.get("name", preset["name"])
    assert stored["is_default"] == expected_change.get("is_default", preset["is_default"])
    assert stored["params"]["inference_steps"] == expected_change.get("inference_steps", 8)
    assert not stored["params"].get("reference_audio_path")


@pytest.mark.parametrize("reference", REFUSED_REFERENCES)
def test_defaults_naming_a_reference_are_refused_as_a_whole(
    admin_client: TestClient,
    reference: str,
) -> None:
    before = admin_client.get(DEFAULTS).json()

    response = admin_client.put(
        DEFAULTS,
        json={
            "turbo": {"shift": 4},
            "sft": {"reference_audio_path": reference},
        },
    )

    assert response.status_code == 422
    assert admin_client.get(DEFAULTS).json() == before


@pytest.mark.parametrize("sft", ACCEPTED_PARAMS)
def test_defaults_without_a_reference_are_stored_as_sent(
    admin_client: TestClient, sft: dict
) -> None:
    response = admin_client.put(DEFAULTS, json={"sft": sft})

    assert response.status_code == 200
    stored = admin_client.get(DEFAULTS).json()
    assert stored["sft"].get("inference_steps") == sft.get("inference_steps")
    assert not stored["sft"].get("reference_audio_path")
