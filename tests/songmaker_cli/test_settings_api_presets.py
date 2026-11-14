"""The preset routes refuse a name clash and an id that is not the person's own."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from support.signed_in_people import sign_in_people
from support.web_app import refusal_body

from songmaker_cli.db.models import AvailableModel, GenerationPreset
from songmaker_cli.settings_api import PRESET_NAME_EXISTS_DETAIL

PRESETS_URL = "/api/settings/presets"


@pytest.fixture
def people(tmp_path, pg_factory):
    clients = sign_in_people(
        tmp_path, pg_factory, {"ana": "user", "ben": "user", "root": "admin"},
    )
    with pg_factory() as session:
        session.get(AvailableModel, "turbo").is_active = True
        session.commit()
    return clients, pg_factory


def _create(client: TestClient, name: str, model: str = "sft", **extra) -> dict:
    response = client.post(
        PRESETS_URL, json={"name": name, "model_mode": model, "params": {}, **extra},
    )
    assert response.status_code == 200
    return response.json()


def _shared_preset(factory) -> str:
    with factory() as session:
        shared = GenerationPreset(name="shared", model_mode="sft", params={}, created_by=None)
        session.add(shared)
        session.commit()
        return shared.id


def _stored_presets(factory) -> dict[str, tuple[str, str | None, bool]]:
    with factory() as session:
        owned = session.query(GenerationPreset).filter(GenerationPreset.created_by.isnot(None))
        return {row.id: (row.name, row.created_by, row.is_default) for row in owned}


def test_a_second_preset_with_the_same_name_and_model_is_refused(people):
    clients, factory = people
    _create(clients["ana"], "warm")
    before = _stored_presets(factory)

    response = clients["ana"].post(
        PRESETS_URL, json={"name": "warm", "model_mode": "sft", "params": {}},
    )

    assert (response.status_code, response.json()["detail"]) == (409, PRESET_NAME_EXISTS_DETAIL)
    assert response.json()["message"] == {"key": "presetRefusal.nameTaken", "values": {}}
    assert _stored_presets(factory) == before


def test_another_person_or_another_model_may_reuse_a_preset_name(people):
    clients, factory = people
    _create(clients["ana"], "warm")

    _create(clients["ben"], "warm")
    _create(clients["ana"], "warm", model="turbo")

    assert sorted(name for name, _, _ in _stored_presets(factory).values()) == ["warm"] * 3


def test_an_own_preset_is_updated(people):
    clients, factory = people
    preset = _create(clients["ana"], "warm")

    response = clients["ana"].put(f"{PRESETS_URL}/{preset['id']}", json={"name": "cool"})

    assert response.status_code == 200
    assert _stored_presets(factory)[preset["id"]][0] == "cool"


@pytest.mark.parametrize("person", ["ben", "root"])
@pytest.mark.parametrize("target", ["foreign", "shared", "unknown"])
def test_an_id_that_is_not_the_persons_own_is_not_found_on_every_preset_route(
    people, person, target,
):
    clients, factory = people
    preset_id = {
        "foreign": lambda: _create(clients["ana"], "warm")["id"],
        "shared": lambda: _shared_preset(factory),
        "unknown": lambda: "00000000-0000-0000-0000-00000000dead",
    }[target]()
    before = _stored_presets(factory)
    client = clients[person]

    responses = [
        client.put(f"{PRESETS_URL}/{preset_id}", json={"name": "taken"}),
        client.delete(f"{PRESETS_URL}/{preset_id}"),
        client.post(f"{PRESETS_URL}/{preset_id}/set-default"),
    ]

    assert [(r.status_code, r.json()) for r in responses] == [
        (404, refusal_body("presetRefusal.notFound")),
    ] * 3
    assert _stored_presets(factory) == before
    with factory() as session:
        assert (session.get(GenerationPreset, preset_id) is not None) == (target != "unknown")


@pytest.mark.parametrize("body", [{}, {"name": "warm"}], ids=["no name", "own name"])
def test_an_update_without_a_new_name_changes_params_and_default_without_a_clash(people, body):
    clients, factory = people
    preset = _create(clients["ana"], "warm")

    response = clients["ana"].put(
        f"{PRESETS_URL}/{preset['id']}", json={**body, "is_default": True},
    )

    assert response.status_code == 200
    assert _stored_presets(factory)[preset["id"]] == ("warm", "u-ana", True)


def test_a_rename_onto_another_preset_of_the_same_model_is_refused(people):
    clients, factory = people
    _create(clients["ana"], "warm")
    cool = _create(clients["ana"], "cool")
    before = _stored_presets(factory)

    response = clients["ana"].put(f"{PRESETS_URL}/{cool['id']}", json={"name": "warm"})

    assert (response.status_code, response.json()["detail"]) == (409, PRESET_NAME_EXISTS_DETAIL)
    assert response.json()["message"] == {"key": "presetRefusal.nameTaken", "values": {}}
    assert _stored_presets(factory) == before


def test_a_rename_onto_a_name_of_another_model_goes_through(people):
    clients, factory = people
    _create(clients["ana"], "warm", model="turbo")
    cool = _create(clients["ana"], "cool")

    response = clients["ana"].put(f"{PRESETS_URL}/{cool['id']}", json={"name": "warm"})

    assert response.status_code == 200
    assert _stored_presets(factory)[cool["id"]][0] == "warm"


def test_an_update_cannot_change_the_model(people):
    clients, factory = people
    preset = _create(clients["ana"], "warm")

    response = clients["ana"].put(f"{PRESETS_URL}/{preset['id']}", json={"model_mode": "turbo"})

    assert response.status_code == 200
    with factory() as session:
        assert session.get(GenerationPreset, preset["id"]).model_mode == "sft"


def test_deleting_an_own_preset_removes_only_it(people):
    clients, factory = people
    mine = _create(clients["ana"], "warm")
    theirs = _create(clients["ben"], "warm")

    assert clients["ana"].delete(f"{PRESETS_URL}/{mine['id']}").status_code == 200

    assert set(_stored_presets(factory)) == {theirs["id"]}


def test_setting_an_own_preset_as_default_clears_the_previous_one(people):
    clients, factory = people
    first = _create(clients["ana"], "first", is_default=True)
    second = _create(clients["ana"], "second")
    bens = _create(clients["ben"], "bens", is_default=True)

    response = clients["ana"].post(f"{PRESETS_URL}/{second['id']}/set-default")

    assert response.status_code == 200
    defaults = {preset_id: row[2] for preset_id, row in _stored_presets(factory).items()}
    assert defaults == {first["id"]: False, second["id"]: True, bens["id"]: True}


@pytest.mark.parametrize(
    ("body", "stored_params", "stored_default"),
    [
        ({"params": {"inference_steps": 12}}, {"inference_steps": 12}, True),
        ({"is_default": False}, {}, False),
    ],
    ids=["new params", "default cleared"],
)
def test_an_update_changes_only_what_it_sends(people, body, stored_params, stored_default):
    clients, _ = people
    preset = _create(clients["ana"], "warm", is_default=True)

    response = clients["ana"].put(f"{PRESETS_URL}/{preset['id']}", json=body)

    assert response.status_code == 200
    (listed,) = clients["ana"].get(PRESETS_URL).json()
    assert listed["params"] == stored_params
    assert listed["is_default"] is stored_default


def test_a_preset_for_a_model_the_app_does_not_offer_is_refused(people):
    clients, factory = people

    response = clients["ana"].post(
        PRESETS_URL, json={"name": "warm", "model_mode": "nomodel", "params": {}},
    )

    assert response.status_code == 422
    assert not _stored_presets(factory)
