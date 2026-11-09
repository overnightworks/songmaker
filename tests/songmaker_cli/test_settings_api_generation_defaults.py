"""The generation-defaults route refuses a body that is not keyed by an offered model."""

from __future__ import annotations

import pytest
from support.signed_in_people import sign_in_people

DEFAULTS_URL = "/api/settings/generation-defaults"


@pytest.fixture
def admin(tmp_path, pg_factory):
    return sign_in_people(tmp_path, pg_factory, {"root": "admin"})["root"]


@pytest.mark.parametrize(
    "body",
    [[{"inference_steps": 12}], {"nomodel": {"inference_steps": 12}}],
    ids=["a list", "an unknown model"],
)
def test_a_body_not_keyed_by_an_offered_model_is_refused_and_saves_nothing(admin, body):
    saved = {"turbo": {"inference_steps": 12}}
    assert admin.put(DEFAULTS_URL, json=saved).status_code == 200

    response = admin.put(DEFAULTS_URL, json=body)

    assert response.status_code == 422
    assert admin.get(DEFAULTS_URL).json() == saved
