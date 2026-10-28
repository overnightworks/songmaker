"""Version writes and version deletes on one song serialize on the song row (PostgreSQL)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import make_authenticated_user, make_test_app, seed_session
from postgres_lock_harness import race

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, Song, User, Version
from songmaker_cli.db.queries.songs import create_song, update_song
from songmaker_cli.mcp_server.tools import tool_rename_song, tool_update_song_lyrics

OWNER = "u1"
OWNER_USER = make_authenticated_user(OWNER, username="owner")
FILES = {name: f"{OWNER}/{REFERENCE_AUDIO_DIR}/{name}.wav" for name in "FGH"}
EDITOR_LEGS = {
    "names reference G": {"generation_params": {"reference_audio_path": FILES["G"]}},
    "names none": {"lyrics": "edited"},
}
EDITED = "edited"


def _seeded(references: list[str]):
    """Seed an owner and a song whose versions v1, v2, ... name ``references``."""
    def seed(session) -> None:
        session.add(User(id=OWNER, username="owner"))
        session.flush()
        session.add(Album(id="album-a", title="A", artist="A", created_by=OWNER))
        session.flush()
        song = create_song(
            session, "Original", "album-a", "original", created_by=OWNER,
            generation_params={"reference_audio_path": references[0]},
        )
        for number, reference in enumerate(references[1:], start=2):
            update_song(
                session, song.id, lyrics=f"lyrics {number}", force_new_version=True,
                generation_params={"reference_audio_path": reference},
            )

    return seed


class _World:
    """One song on PostgreSQL, written through the editor's routes and the co-writer's tools."""

    def __init__(self, pg_factory, tmp_path: Path, references: list[str]) -> None:
        self.pg_factory = pg_factory
        self.client, _ = make_test_app(tmp_path, factory=pg_factory, seed_db=_seeded(references))
        seed_session(self.client, "owner")
        for file in FILES.values():
            path = tmp_path / "audio" / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"RIFF")
        with pg_factory() as session:
            self.song_id = session.query(Song).one().id

    def edit(self, leg: str):
        return lambda: self.client.put(f"/api/songs/{self.song_id}", json=EDITOR_LEGS[leg])

    def delete_version(self, number: int):
        with self.pg_factory() as session:
            version_id = session.query(Version).filter_by(version_number=number).one().id
        return lambda: self.client.delete(f"/api/versions/{version_id}")

    def cowrite(self, tool, *arguments: Any):
        def run() -> None:
            with self.pg_factory() as session:
                tool(session, OWNER_USER, self.song_id, *arguments)
                session.commit()

        return run

    def versions(self) -> dict[int, tuple[str, str | None]]:
        """Version number to its lyrics and the reference it names."""
        with self.pg_factory() as session:
            return {
                version.version_number: (
                    version.lyrics, (version.generation_params or {}).get("reference_audio_path"),
                )
                for version in session.query(Version)
            }

    def title_and_slug(self) -> tuple[str, str]:
        with self.pg_factory() as session:
            song = session.query(Song).one()
            return song.title, song.slug


def _edited(leg: str, lyrics: str, reference: str) -> tuple[str, str]:
    """The lyrics and reference a version holds once the editor's leg applied to it in place."""
    return (EDITED, reference) if leg == "names none" else (lyrics, FILES["G"])


@pytest.mark.parametrize("leg", list(EDITOR_LEGS))
def test_b1_a_copy_forward_waits_for_an_in_place_save_and_carries_its_params(
    pg_factory, tmp_path, leg,
) -> None:
    world = _World(pg_factory, tmp_path, [FILES["F"]])
    race(pg_factory, world.edit(leg), world.cowrite(tool_update_song_lyrics, "co-written"))
    assert world.versions() == {
        1: _edited(leg, "", FILES["F"]),
        2: ("co-written", _edited(leg, "", FILES["F"])[1]),
    }


@pytest.mark.parametrize("leg", list(EDITOR_LEGS))
def test_b2_an_in_place_save_waits_for_a_copy_forward_and_applies_to_the_new_version(
    pg_factory, tmp_path, leg,
) -> None:
    world = _World(pg_factory, tmp_path, [FILES["F"]])
    race(pg_factory, world.cowrite(tool_update_song_lyrics, "co-written"), world.edit(leg))
    assert world.versions() == {1: ("", FILES["F"]), 2: _edited(leg, "co-written", FILES["F"])}


def test_b3_a_copy_forward_waits_for_a_version_delete_and_carries_the_remaining_params(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, [FILES["H"], FILES["F"]])
    answers = race(
        pg_factory, world.delete_version(2), world.cowrite(tool_update_song_lyrics, "co-written"),
    )
    assert answers["first"].status_code == 200
    assert world.versions() == {1: ("", FILES["H"]), 2: ("co-written", FILES["H"])}


def test_b4_a_version_delete_waits_for_a_copy_forward_and_leaves_the_new_version(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, [FILES["H"], FILES["F"]])
    answers = race(
        pg_factory, world.cowrite(tool_update_song_lyrics, "co-written"), world.delete_version(2),
    )
    assert answers["second"].status_code == 200
    assert world.versions() == {1: ("", FILES["H"]), 3: ("co-written", FILES["F"])}


@pytest.mark.parametrize("rename_first", [True, False], ids=["rename first", "update first"])
@pytest.mark.parametrize("leg", list(EDITOR_LEGS))
def test_b5_a_rename_keeps_its_title_and_slug_against_an_editor_save_in_both_orders(
    pg_factory, tmp_path, leg, rename_first,
) -> None:
    world = _World(pg_factory, tmp_path, [FILES["F"]])
    rename = world.cowrite(tool_rename_song, "Renamed")
    editor = world.edit(leg)
    race(pg_factory, *((rename, editor) if rename_first else (editor, rename)))
    assert world.title_and_slug() == ("Renamed", "renamed")
    edited = _edited(leg, "", FILES["F"])
    assert world.versions() == {1: ("", FILES["F"]) if rename_first else edited, 2: edited}


def test_b6_a_second_delete_of_one_version_waits_and_then_answers_not_found(
    pg_factory, tmp_path,
) -> None:
    world = _World(pg_factory, tmp_path, [FILES["H"], FILES["F"]])
    answers = race(pg_factory, world.delete_version(2), world.delete_version(2))
    assert answers["first"].status_code == 200
    assert answers["second"].status_code == 404
    assert answers["second"].json() == {"detail": "Version not found"}
    assert world.versions() == {1: ("", FILES["H"])}
