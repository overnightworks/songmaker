"""GET /api/references/{id}/uses: where a reference is linked, for its owner only."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support import reference_api_world
from support.reference_api_world import (
    LINKS,
    NOT_FOUND,
    REFERENCES_PATH,
    link_reference,
    post_reference,
    seed_reference,
    signed_in_as,
)
from support.token_world import TokenWorld, make_token_world
from support.web_app import TEST_ORIGIN

signed_in = reference_api_world.signed_in


def _uses_path(reference_id: str) -> str:
    return f"{REFERENCES_PATH}/{reference_id}/uses"


def _listed_counts(client: TestClient, reference_id: str) -> tuple[int, int]:
    [row] = [
        item for item in client.get(REFERENCES_PATH).json()["references"]
        if item["id"] == reference_id
    ]
    assert row["in_use"] is (row["used_by_versions"] + row["used_by_takes"] > 0)
    return row["used_by_versions"], row["used_by_takes"]


def test_a_linked_version_is_listed_with_its_song_album_and_version_number(
    signed_in: TestClient,
) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    link_reference(
        signed_in, reference_id, via="version", title="Dawn", slug="dawn", version_number=3,
    )

    body = signed_in.get(_uses_path(reference_id)).json()

    assert body == {
        "versions": [{
            "song_id": "song-link", "song_title": "Dawn", "song_slug": "dawn",
            "album_id": "album-link", "version_number": 3, "is_trashed": False,
        }],
        "takes": [],
    }


def test_a_linked_take_is_listed_with_its_numbers_and_duration(signed_in: TestClient) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    link_reference(
        signed_in, reference_id, via="take", title="Dusk", slug="dusk", version_number=2,
        generation_number=5, duration_sec=61.5,
    )

    body = signed_in.get(_uses_path(reference_id)).json()

    assert body == {
        "versions": [],
        "takes": [{
            "song_id": "song-link", "song_title": "Dusk", "song_slug": "dusk",
            "album_id": "album-link", "generation_number": 5, "version_number": 2,
            "is_archived": False, "is_trashed": False, "audio_duration_sec": 61.5,
        }],
    }


def test_an_archived_take_is_marked_archived(signed_in: TestClient) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    link_reference(signed_in, reference_id, via="take", archived=True)

    [take] = signed_in.get(_uses_path(reference_id)).json()["takes"]

    assert take["is_archived"] is True
    assert take["is_trashed"] is False


def test_a_take_without_a_version_is_listed_and_counted(signed_in: TestClient) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    link_reference(signed_in, reference_id, via="take", versionless=True)

    takes = signed_in.get(_uses_path(reference_id)).json()["takes"]

    assert [take["version_number"] for take in takes] == [None]
    assert _listed_counts(signed_in, reference_id) == (0, len(takes))


def test_links_are_listed_newest_first(signed_in: TestClient) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    for key, day in (("old", 1), ("new", 3), ("mid", 2)):
        stamp = datetime(2026, 10, day, tzinfo=timezone.utc)
        link_reference(signed_in, reference_id, via="version", key=key, created_at=stamp)
        link_reference(
            signed_in, reference_id, via="take", key=f"t-{key}", created_at=stamp,
        )

    body = signed_in.get(_uses_path(reference_id)).json()

    assert [use["song_id"] for use in body["versions"]] == ["song-new", "song-mid", "song-old"]
    assert [use["song_id"] for use in body["takes"]] == [
        "song-t-new", "song-t-mid", "song-t-old",
    ]


@pytest.mark.parametrize("link", LINKS)
def test_every_link_the_list_counts_is_listed_and_trashed_ones_are_marked(
    signed_in: TestClient, link: dict,
) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    link_reference(signed_in, reference_id, **link)

    body = signed_in.get(_uses_path(reference_id)).json()

    assert _listed_counts(signed_in, reference_id) == (len(body["versions"]), len(body["takes"]))
    [use] = body["versions"] + body["takes"]
    assert use["is_trashed"] is bool(link.get("song_trashed") or link.get("album_trashed"))


def test_an_unused_reference_has_no_uses_and_zero_counts(signed_in: TestClient) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")

    assert signed_in.get(_uses_path(reference_id)).json() == {"versions": [], "takes": []}
    assert _listed_counts(signed_in, reference_id) == (0, 0)


def test_a_reference_linked_by_two_versions_and_a_take_counts_each_kind(
    signed_in: TestClient,
) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    link_reference(signed_in, reference_id, via="version", key="a")
    link_reference(signed_in, reference_id, via="version", key="b")
    link_reference(signed_in, reference_id, via="take", key="c")

    assert _listed_counts(signed_in, reference_id) == (2, 1)


@pytest.mark.parametrize("caller", ["other", "boss"])
def test_a_foreign_reference_is_not_found_even_for_an_admin(
    signed_in: TestClient, caller: str,
) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    link_reference(signed_in, reference_id, via="take")

    response = signed_in_as(signed_in, caller).get(_uses_path(reference_id))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_an_unknown_id_is_not_found(signed_in: TestClient) -> None:
    response = signed_in.get(_uses_path("no-such-id"))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_without_a_session_the_uses_are_unauthenticated(signed_in: TestClient) -> None:
    reference_id = seed_reference(signed_in, "owner-id", "ref.wav")
    anonymous = TestClient(signed_in.app, base_url=TEST_ORIGIN, raise_server_exceptions=False)

    assert anonymous.get(_uses_path(reference_id)).status_code == 401


def test_a_persons_token_reads_the_uses_of_that_persons_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pg_factory,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = make_token_world(tmp_path, factory=pg_factory)
    reference_id = post_reference(
        world.client, headers=world.bearer(TokenWorld.ALICE),
    ).json()["id"]

    response = world.client.get(_uses_path(reference_id), headers=world.bearer(TokenWorld.ALICE))

    assert response.status_code == 200, response.text
    assert response.json() == {"versions": [], "takes": []}
