"""Presets and global generation defaults refuse a non-empty reference upload."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_authenticated_user, make_router_app, make_router_ctx, web_client
from fastapi.testclient import TestClient

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import User

PRESETS = "/api/settings/presets"
DEFAULTS = "/api/settings/generation-defaults"

REFUSED_REFERENCES = ["u1/refs/a.wav", "x", " "]
ACCEPTED_PARAMS = [
    pytest.param({"reference_audio_path": ""}, id="empty-string"),
    pytest.param({"reference_audio_path": None}, id="null"),
    pytest.param({"inference_steps": 8}, id="absent-key"),
]


@pytest.fixture
def admin(tmp_path: Path) -> TestClient:
    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id="u-admin", username="admin", role="admin"))
        session.commit()
    app = make_router_app(
        make_router_ctx(tmp_path, db=factory),
        user=make_authenticated_user("u-admin", role="admin", username="admin"),
    )
    return web_client(app)


def _create_preset(client: TestClient, params: dict) -> object:
    return client.post(PRESETS, json={"name": "p", "model_mode": "sft", "params": params})


@pytest.mark.parametrize("reference", REFUSED_REFERENCES)
def test_create_preset_naming_a_reference_is_refused_and_stores_nothing(
    admin: TestClient, reference: str,
) -> None:
    response = _create_preset(admin, {"reference_audio_path": reference})

    assert response.status_code == 422
    assert admin.get(PRESETS).json() == []


@pytest.mark.parametrize("params", ACCEPTED_PARAMS)
def test_create_preset_without_a_reference_is_accepted(admin: TestClient, params: dict) -> None:
    response = _create_preset(admin, params)

    assert response.status_code == 200
    assert [preset["id"] for preset in admin.get(PRESETS).json()] == [response.json()["id"]]


@pytest.mark.parametrize("reference", REFUSED_REFERENCES)
def test_update_preset_naming_a_reference_is_refused_and_keeps_the_stored_params(
    admin: TestClient, reference: str,
) -> None:
    preset = _create_preset(admin, {"inference_steps": 8}).json()

    response = admin.put(
        f"{PRESETS}/{preset['id']}", json={"params": {"reference_audio_path": reference}},
    )

    assert response.status_code == 422
    stored = next(item for item in admin.get(PRESETS).json() if item["id"] == preset["id"])
    assert stored["params"] == preset["params"]


@pytest.mark.parametrize(
    "update",
    [
        pytest.param({"name": "renamed"}, id="name-only"),
        pytest.param({"is_default": True}, id="is-default-only"),
        pytest.param({"params": None}, id="null-params"),
        pytest.param({"params": {"inference_steps": 9}}, id="params-without-key"),
        pytest.param({"params": {"reference_audio_path": ""}}, id="empty-reference"),
        pytest.param({"params": {"reference_audio_path": None}}, id="null-reference"),
    ],
)
def test_update_preset_without_a_reference_is_accepted(admin: TestClient, update: dict) -> None:
    preset = _create_preset(admin, {"inference_steps": 8}).json()

    response = admin.put(f"{PRESETS}/{preset['id']}", json=update)

    assert response.status_code == 200


@pytest.mark.parametrize("reference", REFUSED_REFERENCES)
def test_defaults_naming_a_reference_are_refused_as_a_whole(
    admin: TestClient, reference: str,
) -> None:
    before = admin.get(DEFAULTS).json()

    response = admin.put(DEFAULTS, json={
        "turbo": {"shift": 4},
        "sft": {"reference_audio_path": reference},
    })

    assert response.status_code == 422
    assert admin.get(DEFAULTS).json() == before


@pytest.mark.parametrize("sft", ACCEPTED_PARAMS)
def test_defaults_without_a_reference_are_stored_as_sent(admin: TestClient, sft: dict) -> None:
    response = admin.put(DEFAULTS, json={"sft": sft})

    assert response.status_code == 200
    stored = admin.get(DEFAULTS).json()
    assert stored == response.json()
    assert stored["sft"].get("reference_audio_path", "") in ("", None)
