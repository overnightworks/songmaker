"""Tests for the E2E take seeders in ``scripts/``."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, User

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import seed_e2e_job_states  # noqa: E402
import seed_e2e_song_takes  # noqa: E402

_OWNER_ID = "owner"
_ALBUM_ID = "album"


def _seed_song_takes(session, audio_dir: Path) -> str:
    return seed_e2e_song_takes.seed_song_takes(
        session, audio_dir, b"mp3",
        album_id=_ALBUM_ID, title="Takes", take_count=2, owner_id=_OWNER_ID,
    )


def _seed_song_at_version(session, audio_dir: Path) -> str:
    return seed_e2e_job_states.seed_song_at_version(
        session, audio_dir, b"mp3",
        album_id=_ALBUM_ID, title="Takes", version_number=2, take_count=2,
        owner_id=_OWNER_ID,
    )


@pytest.mark.parametrize("seed", [_seed_song_takes, _seed_song_at_version])
def test_seeded_takes_record_the_owner_as_their_maker(
    tmp_path: Path, seed: Callable[..., str],
) -> None:
    audio_dir = tmp_path / "audio"
    factory = init_test_db(tmp_path / "seed.db")
    with factory() as session:
        session.add(User(id=_OWNER_ID, username=_OWNER_ID, password_hash="x"))
        session.add(Album(id=_ALBUM_ID, title="A", artist="X"))
        session.commit()

        song_id = seed(session, audio_dir)

        makers = {g.created_by for g in session.query(Generation).filter_by(song_id=song_id)}
        assert makers == {_OWNER_ID}
