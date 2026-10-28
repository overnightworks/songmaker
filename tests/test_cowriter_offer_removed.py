"""The co-writer offer route is gone."""

from __future__ import annotations

from conftest import make_test_app


def test_the_removed_offer_path_answers_404(tmp_path):
    client, _factory = make_test_app(tmp_path)

    assert client.get("/api/settings/cowriter/offer").status_code == 404
