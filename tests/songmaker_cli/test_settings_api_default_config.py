"""A default config that names a deleted preset reads as inherit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from support.signed_in_people import sign_in_people

from songmaker_cli.db.models import GenerationPreset, User

DEFAULT_CONFIG_URL = "/api/settings/default-config"
PRESETS_URL = "/api/settings/presets"
DEAD_PRESET_ID = "00000000-0000-0000-0000-00000000dead"


@pytest.fixture
def people(tmp_path, pg_factory):
    clients = sign_in_people(tmp_path, pg_factory, {"ana": "user", "ben": "user"})
    return clients, pg_factory


def _preset(client: TestClient, name: str) -> str:
    return client.post(
        PRESETS_URL, json={"name": name, "model_mode": "sft", "params": {}},
    ).json()["id"]


def test_deleting_the_default_preset_leaves_inherit(people):
    clients, _ = people
    ana = clients["ana"]
    preset_id = _preset(ana, "mine")
    ana.put(DEFAULT_CONFIG_URL, json={"config": preset_id})

    assert ana.delete(f"{PRESETS_URL}/{preset_id}").status_code == 200

    assert ana.get(DEFAULT_CONFIG_URL).json() == {"config": None}


def test_a_dead_id_stored_directly_reads_as_inherit(people):
    clients, factory = people
    with factory() as session:
        session.get(User, "u-ana").default_generation_config = DEAD_PRESET_ID
        session.commit()

    assert clients["ana"].get(DEFAULT_CONFIG_URL).json() == {"config": None}


def test_deleting_another_preset_leaves_the_default(people):
    clients, _ = people
    ana = clients["ana"]
    kept, other = _preset(ana, "kept"), _preset(ana, "other")
    ana.put(DEFAULT_CONFIG_URL, json={"config": kept})

    ana.delete(f"{PRESETS_URL}/{other}")

    assert ana.get(DEFAULT_CONFIG_URL).json() == {"config": kept}


def test_a_built_in_default_survives_a_preset_delete(people):
    clients, _ = people
    ana = clients["ana"]
    ana.put(DEFAULT_CONFIG_URL, json={"config": "turbo"})

    ana.delete(f"{PRESETS_URL}/{_preset(ana, 'mine')}")

    assert ana.get(DEFAULT_CONFIG_URL).json() == {"config": "turbo"}


def test_a_shared_preset_is_accepted_as_default(people):
    clients, factory = people
    with factory() as session:
        shared = GenerationPreset(name="shared", model_mode="sft", params={}, created_by=None)
        session.add(shared)
        session.commit()
        shared_id = shared.id

    response = clients["ana"].put(DEFAULT_CONFIG_URL, json={"config": shared_id})

    assert response.status_code == 200
    assert clients["ana"].get(DEFAULT_CONFIG_URL).json() == {"config": shared_id}


def test_another_persons_preset_is_refused_as_default(people):
    clients, factory = people
    foreign = _preset(clients["ben"], "bens")

    response = clients["ana"].put(DEFAULT_CONFIG_URL, json={"config": foreign})

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Invalid config: must be null, 'sft', 'turbo', or a preset ID"
    )
    with factory() as session:
        assert session.get(User, "u-ana").default_generation_config is None
