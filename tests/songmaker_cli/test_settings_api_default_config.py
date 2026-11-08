"""A default config that names a deleted preset reads as inherit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from support.web_app import make_authenticated_user, make_router_app, make_router_ctx, web_client

from songmaker_cli.db.models import User

DEFAULT_CONFIG_URL = "/api/settings/default-config"
PRESETS_URL = "/api/settings/presets"
DEAD_PRESET_ID = "00000000-0000-0000-0000-00000000dead"


@pytest.fixture
def people(tmp_path, pg_factory):
    def seed(session) -> None:
        session.add_all([User(id="u-ana", username="ana"), User(id="u-ben", username="ben")])

    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=seed)
    clients = {
        name: web_client(make_router_app(ctx, user=make_authenticated_user(f"u-{name}")))
        for name in ("ana", "ben")
    }
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
