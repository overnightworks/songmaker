"""A database holding one person's album, song and take, and the verdict tool run against it."""

from __future__ import annotations

from songmaker_cli.cowriter.tools import execute_cowriter_tool
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.mcp_server import auth


def seed_verdict_world(session_factory):
    with session_factory() as session:
        session.add_all([
            User(id="anna", username="anna", role="user"),
            User(id="ben", username="ben", role="user"),
        ])
        session.flush()
        session.add(Album(id="album-anna", title="Nachtzug", artist="Anna", created_by="anna"))
        session.add(Song(id="song-anna", title="Nachtzug", album_id="album-anna", track_number=1))
        session.add(Version(
            id="version-anna", song_id="song-anna", version_number=1,
            lyrics="la la", prompt="rock",
        ))
        session.commit()
    return session_factory


def add_take(factory, generation_id, *, whisper_text="la la", batch=None, archived=False):
    with factory() as session:
        session.add(Generation(
            id=generation_id, song_id="song-anna", version_id="version-anna",
            generation_number=1, mp3_path=f"anna/{generation_id}.mp3",
            whisper_text=whisper_text, is_archived=archived,
        ))
        if batch is not None:
            session.add(Score(generation_id=generation_id, scorer="batch", value=batch))
        session.commit()


def stored_scores(factory, generation_id):
    with factory() as session:
        rows = session.query(Score).filter_by(generation_id=generation_id).all()
        return [(row.scorer, dict(row.value)) for row in rows]


def save_verdict(factory, generation_id, score, summary, user="anna"):
    with factory() as session:
        return execute_cowriter_tool(
            session, auth.load_user(session, user), "save_coherence_verdict",
            {"generation_id": generation_id, "score": score, "summary": summary},
        )
