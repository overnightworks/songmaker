"""One owner with a song, a version and a running job, and the persistence of a take that links."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from acestep_engine.models import AceStepConfig
from songmaker_cli.db.models import Album, Job, Song, User, Version
from songmaker_cli.jobs import _persist_generation_row
from songmaker_cli.jobs._runtime import ReferenceDeletedDuringTake
from songmaker_cli.jobs.generation import GenerationContext
from songmaker_cli.parser import AlbumMeta, SongMeta


def seed_owner_song_and_running_job(session: Session, owner: str) -> None:
    """Add ``owner`` with ``album-a``, ``song-a``, ``version-a`` and the running ``job-a``."""
    session.add(User(id=owner, username="owner"))
    session.flush()
    session.add(Album(id="album-a", title="A", artist="A", created_by=owner))
    session.flush()
    session.add(Song(id="song-a", title="S", album_id="album-a", track_number=1, slug="s"))
    session.flush()
    session.add_all([
        Version(id="version-a", song_id="song-a", version_number=1, lyrics="la", prompt="p"),
        Job(id="job-a", type="generate", status="running", user_id=owner),
    ])


def persist_take_linking(
    factory: sessionmaker[Session], audio_dir: Path, owner: str, reference_id: str,
) -> object:
    """Persist ``take-a`` linking the reference; the message that ends the job is the answer."""
    context = GenerationContext(
        song_id="song-a", version_id="version-a",
        meta=SongMeta(title="S", lyrics="la", prompt="p"),
        album_meta=AlbumMeta(title="A", artist="A"),
        ace_config=AceStepConfig(prompt="p", lyrics="la", audio_duration=0),
        audio_dir=audio_dir, user_id=owner, reference_recording_id=reference_id,
        model_name="turbo",
    )
    try:
        return _persist_generation_row(
            db_factory=factory, ctx=context, generation_id="take-a", seed=1,
            cot_caption="", cot_lyrics="", delivered_batch_size=None, job_id="job-a",
        )
    except ReferenceDeletedDuringTake as failure:
        return str(failure)
