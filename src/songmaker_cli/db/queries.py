"""Database query functions — called by API endpoints."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import Album, Generation, Rating, Song, Version


def list_albums(session: Session) -> list[Album]:
    return session.query(Album).order_by(Album.title).all()


def get_album(session: Session, album_id: str) -> Album | None:
    return session.query(Album).filter_by(id=album_id).first()


def list_songs(session: Session, album_id: str | None = None) -> list[Song]:
    query = (
        session.query(Song)
        .options(
            joinedload(Song.versions),
            joinedload(Song.generations).joinedload(Generation.scores),
            joinedload(Song.generations).joinedload(Generation.rating),
            joinedload(Song.album),
        )
        .order_by(Song.album_id, Song.track_number)
    )
    if album_id:
        query = query.filter_by(album_id=album_id)
    return query.all()


def get_song(session: Session, song_id: str) -> Song | None:
    return (
        session.query(Song)
        .options(
            joinedload(Song.versions),
            joinedload(Song.generations).joinedload(Generation.scores),
            joinedload(Song.generations).joinedload(Generation.rating),
            joinedload(Song.album),
        )
        .filter_by(id=song_id)
        .first()
    )


def get_generation(session: Session, gen_id: str) -> Generation | None:
    return (
        session.query(Generation)
        .options(
            joinedload(Generation.scores),
            joinedload(Generation.rating),
            joinedload(Generation.song).joinedload(Song.album),
        )
        .filter_by(id=gen_id)
        .first()
    )


def get_generation_by_path(session: Session, mp3_path: str) -> Generation | None:
    return (
        session.query(Generation)
        .options(joinedload(Generation.scores), joinedload(Generation.rating))
        .filter_by(mp3_path=mp3_path)
        .first()
    )


def save_rating(
    session: Session, generation_id: str, rating_value: float, notes: str = "",
) -> Rating:
    existing = session.query(Rating).filter_by(generation_id=generation_id).first()
    if existing:
        existing.rating = rating_value
        existing.notes = notes
        session.flush()
        return existing

    rating = Rating(generation_id=generation_id, rating=rating_value, notes=notes)
    session.add(rating)
    session.flush()
    return rating


def create_song(
    session: Session,
    title: str,
    album_id: str,
    lyrics: str = "",
    prompt: str = "",
    bpm: int = 0,
    duration: int = 180,
    key: str = "",
    language: str = "",
) -> Song:
    album = session.query(Album).filter_by(id=album_id).first()
    if not album:
        raise ValueError(f"Album not found: {album_id}")

    max_track = (
        session.query(Song.track_number)
        .filter_by(album_id=album_id)
        .order_by(Song.track_number.desc())
        .first()
    )
    track_number = (max_track[0] + 1) if max_track else 1

    song = Song(
        title=title, album_id=album_id, language=language, track_number=track_number,
    )
    session.add(song)
    session.flush()

    version = Version(
        song_id=song.id, version_number=1,
        lyrics=lyrics, prompt=prompt, bpm=bpm, duration=duration, key=key,
    )
    session.add(version)
    session.flush()
    return song


def update_song(
    session: Session,
    song_id: str,
    lyrics: str | None = None,
    prompt: str | None = None,
    bpm: int | None = None,
    duration: int | None = None,
    key: str | None = None,
) -> Version:
    song = get_song(session, song_id)
    if not song:
        raise ValueError(f"Song not found: {song_id}")

    prev = song.latest_version
    next_num = (prev.version_number + 1) if prev else 1

    version = Version(
        song_id=song_id,
        version_number=next_num,
        lyrics=lyrics if lyrics is not None else (prev.lyrics if prev else ""),
        prompt=prompt if prompt is not None else (prev.prompt if prev else ""),
        bpm=bpm if bpm is not None else (prev.bpm if prev else 0),
        duration=duration if duration is not None else (prev.duration if prev else 180),
        key=key if key is not None else (prev.key if prev else ""),
    )
    session.add(version)
    session.flush()
    return version


# ── Deletion ─────────────────────────────────────────────────────────


def delete_version(
    session: Session, version_id: str, *, delete_generations: bool = False,
) -> None:
    version = session.query(Version).filter_by(id=version_id).first()
    if not version:
        raise ValueError(f"Version not found: {version_id}")

    if delete_generations:
        for gen in version.generations:
            session.delete(gen)
    else:
        for gen in version.generations:
            gen.version_id = None

    session.delete(version)
    session.flush()


def delete_generation(session: Session, generation_id: str) -> None:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    session.delete(gen)
    session.flush()


# ── Serialization ────────────────────────────────────────────────────


def generation_to_dict(gen: Generation) -> dict:
    scores_dict: dict[str, object] = {}
    for score in gen.scores:
        if isinstance(score.value, dict):
            scores_dict.update(score.value)

    if gen.rating:
        scores_dict["user_rating"] = gen.rating.rating
        scores_dict["user_notes"] = gen.rating.notes

    return {
        "id": gen.id,
        "song_id": gen.song_id,
        "version_id": gen.version_id,
        "version_number": gen.version.version_number if gen.version else None,
        "generation_number": gen.generation_number,
        "mp3_path": gen.mp3_path,
        "seed": gen.seed,
        "status": gen.status,
        "is_archived": gen.is_archived,
        "whisper_text": gen.whisper_text,
        "scores": scores_dict if scores_dict else None,
        "generation_params": gen.generation_params,
        "created_at": gen.created_at.isoformat() if gen.created_at else None,
    }


def song_to_dict(song: Song) -> dict:
    ver = song.latest_version
    best_gen = _best_generation(song.generations)
    return {
        "id": song.id,
        "title": song.title,
        "album_id": song.album_id,
        "album_title": song.album.title if song.album else "",
        "artist": song.album.artist if song.album else "",
        "track_number": song.track_number,
        "language": song.language,
        "lyrics": ver.lyrics if ver else "",
        "prompt": ver.prompt if ver else "",
        "bpm": ver.bpm if ver else 0,
        "duration": ver.duration if ver else 180,
        "key": ver.key if ver else "",
        "version_count": len(song.versions),
        "generation_count": len(song.generations),
        "best_scores": _extract_scores(best_gen) if best_gen else None,
        "best_rating": best_gen.rating.rating if best_gen and best_gen.rating else None,
        "generations": [generation_to_dict(g) for g in song.generations],
        "created_at": song.created_at.isoformat() if song.created_at else None,
    }


def version_to_dict(ver: Version) -> dict:
    return {
        "id": ver.id,
        "version_number": ver.version_number,
        "lyrics": ver.lyrics,
        "prompt": ver.prompt,
        "bpm": ver.bpm,
        "duration": ver.duration,
        "key": ver.key,
        "created_at": ver.created_at.isoformat() if ver.created_at else None,
    }


def album_to_dict(album: Album) -> dict:
    return {
        "id": album.id,
        "title": album.title,
        "artist": album.artist,
        "subtitle": album.subtitle,
        "year": album.year,
        "colors": album.colors,
        "song_count": len(album.songs) if album.songs else 0,
    }


def _best_generation(generations: list[Generation]) -> Generation | None:
    """Find the generation with the highest user rating, or most recent."""
    rated = [g for g in generations if g.rating and not g.is_archived]
    if rated:
        return max(rated, key=lambda g: g.rating.rating)
    active = [g for g in generations if not g.is_archived]
    return active[0] if active else None


def _extract_scores(gen: Generation) -> dict[str, object]:
    scores: dict[str, object] = {}
    for s in gen.scores:
        if isinstance(s.value, dict):
            scores.update(s.value)
    return scores
