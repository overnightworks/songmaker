"""The built-in parameters, the model lists and the admin's model switch."""

from __future__ import annotations

import pytest
from support.signed_in_people import sign_in_people

from songmaker_cli.config import get_builtin_defaults
from songmaker_cli.constants import AuditAction, ResourceType
from songmaker_cli.db.models import AuditLog, AvailableModel

BUILTINS_URL = "/api/settings/generation-builtins"
ACTIVE_MODELS_URL = "/api/settings/models"
ALL_MODELS_URL = "/api/settings/models/all"
PRESETS_URL = "/api/settings/presets"


@pytest.fixture
def clients(tmp_path, pg_factory):
    return sign_in_people(tmp_path, pg_factory, {"ana": "user", "root": "admin"})


@pytest.fixture
def factory(pg_factory):
    with pg_factory() as session:
        session.get(AvailableModel, "turbo").is_active = True
        session.commit()
    return pg_factory


def _model_audits(factory) -> list[str]:
    with factory() as session:
        rows = session.query(AuditLog).filter_by(
            action=AuditAction.UPDATE, resource_type=ResourceType.MODEL,
        )
        return sorted(f"{row.resource_id}:{row.detail}" for row in rows)


def _stored_activity(factory) -> dict[str, bool]:
    with factory() as session:
        return {row.id: row.is_active for row in session.query(AvailableModel)}


def test_a_member_reads_the_built_in_parameters_of_every_model(clients):

    response = clients["ana"].get(BUILTINS_URL)

    assert response.status_code == 200
    assert response.json() == get_builtin_defaults()


def test_the_admin_lists_every_model_with_the_inactive_ones(clients, factory):
    stored = _stored_activity(factory)
    clients["root"].put(f"{ACTIVE_MODELS_URL}/turbo", params={"active": False})

    response = clients["root"].get(ALL_MODELS_URL)

    assert response.status_code == 200
    assert {item["id"]: item["is_active"] for item in response.json()} == {
        **stored, "turbo": False,
    }


@pytest.mark.parametrize("url", [ALL_MODELS_URL, f"{ACTIVE_MODELS_URL}/turbo"])
def test_a_member_is_refused_the_admin_model_routes(clients, factory, url):
    before = _stored_activity(factory)

    response = (
        clients["ana"].get(url) if url == ALL_MODELS_URL
        else clients["ana"].put(url, params={"active": False})
    )

    assert response.status_code == 403
    assert _stored_activity(factory) == before
    assert _model_audits(factory) == []


@pytest.mark.parametrize("active", [False, True])
def test_the_admin_switches_a_model_and_the_switch_is_audited(clients, factory, active):
    clients["root"].put(f"{ACTIVE_MODELS_URL}/turbo", params={"active": not active})

    response = clients["root"].put(f"{ACTIVE_MODELS_URL}/turbo", params={"active": active})

    body = response.json()
    assert (response.status_code, body["id"], body["is_active"]) == (200, "turbo", active)
    assert _stored_activity(factory)["turbo"] is active
    assert f"turbo:active={active}" in _model_audits(factory)


def test_a_deactivated_model_leaves_the_active_list_and_refuses_a_preset(clients, factory):
    clients["root"].put(f"{ACTIVE_MODELS_URL}/turbo", params={"active": False})

    listed = clients["ana"].get(ACTIVE_MODELS_URL).json()
    refused = clients["ana"].post(
        PRESETS_URL, json={"name": "warm", "model_mode": "turbo", "params": {}},
    )

    assert "turbo" not in {item["id"] for item in listed}
    assert (refused.status_code, refused.json()["detail"]) == (
        400, "Model 'turbo' is not available",
    )
    assert refused.json()["message"] == {
        "key": "settingsRefusal.modelUnavailable", "values": {"mode": "turbo"},
    }


def test_an_unknown_model_id_is_not_found_and_nothing_is_audited(clients, factory):
    before = _stored_activity(factory)

    response = clients["root"].put(f"{ACTIVE_MODELS_URL}/nope", params={"active": False})

    assert (response.status_code, response.json()["detail"]) == (404, "Model not found")
    assert _stored_activity(factory) == before
    assert _model_audits(factory) == []
