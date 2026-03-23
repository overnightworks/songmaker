"""Database query functions — called by API endpoints."""

from __future__ import annotations

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import Album, Rating, Song, SongRevision, Version


def list_albums(session: Session) -> list[Album]:
    return session.query(Album).order_by(Album.title).all()


def get_album(session: Session, album_id: str) -> Album | None:
    return session.query(Album).filter_by(id=album_id).first()


def get_song(session: Session, song_id: str) -> Song | None:
    return (
        session.query(Song)
        .options(joinedload(Song.revisions), joinedload(Song.album))
        .filter_by(id=song_id)
        .first()
    )


def list_versions(session: Session, song_id: str) -> list[Version]:
    return (
        session.query(Version)
        .filter_by(song_id=song_id)
        .options(joinedload(Version.scores), joinedload(Version.rating))
        .order_by(Version.version_number.desc())
        .all()
    )


def get_version(session: Session, version_id: str) -> Version | None:
    return (
        session.query(Version)
        .options(
            joinedload(Version.scores),
            joinedload(Version.rating),
            joinedload(Version.song).joinedload(Song.album),
        )
        .filter_by(id=version_id)
        .first()
    )


def get_version_by_path(session: Session, mp3_path: str) -> Version | None:
    return (
        session.query(Version)
        .options(joinedload(Version.scores), joinedload(Version.rating))
        .filter_by(mp3_path=mp3_path)
        .first()
    )


def list_library(
    session: Session,
    album_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Version], int]:
    """List versions with scores, optionally filtered by album.

    Returns (versions, total_count).
    """
    query = (
        session.query(Version)
        .join(Song)
        .options(
            joinedload(Version.scores),
            joinedload(Version.rating),
            joinedload(Version.song).joinedload(Song.album),
        )
        .filter(Version.is_archived == False)  # noqa: E712
    )

    if album_id:
        query = query.filter(Song.album_id == album_id)

    total = query.count()
    versions = query.order_by(Version.created_at.desc()).offset(offset).limit(limit).all()
    return versions, total


def save_rating(
    session: Session, version_id: str, rating_value: float, notes: str = "",
) -> Rating:
    """Create or update a rating for a version."""
    existing = session.query(Rating).filter_by(version_id=version_id).first()
    if existing:
        existing.rating = rating_value
        existing.notes = notes
        session.flush()
        return existing

    rating = Rating(version_id=version_id, rating=rating_value, notes=notes)
    session.add(rating)
    session.flush()
    return rating


def version_to_dict(version: Version) -> dict:
    """Serialize a Version to a dict for the API response."""
    scores_dict: dict[str, object] = {}
    for score in version.scores:
        if isinstance(score.value, dict):
            scores_dict.update(score.value)

    if version.rating:
        scores_dict["user_rating"] = version.rating.rating
        scores_dict["user_notes"] = version.rating.notes

    gen_params = version.generation_params or {}

    return {
        "id": version.id,
        "song_id": version.song_id,
        "version_number": version.version_number,
        "mp3_path": version.mp3_path,
        "title": version.song.title if version.song else "",
        "album_id": version.song.album_id if version.song else "",
        "album_title": version.song.album.title if version.song and version.song.album else "",
        "artist": version.song.album.artist if version.song and version.song.album else "",
        "track_number": version.song.track_number if version.song else 0,
        "seed": version.seed,
        "status": version.status,
        "is_archived": version.is_archived,
        "whisper_text": version.whisper_text,
        "scores": scores_dict if scores_dict else None,
        "generation": gen_params if gen_params else None,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


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
    """Create a song with its first revision."""
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
        title=title,
        album_id=album_id,
        language=language,
        track_number=track_number,
    )
    session.add(song)
    session.flush()

    revision = SongRevision(
        song_id=song.id,
        lyrics=lyrics,
        prompt=prompt,
        bpm=bpm,
        duration=duration,
        key=key,
    )
    session.add(revision)
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
) -> SongRevision:
    """Update a song by creating a new revision."""
    song = get_song(session, song_id)
    if not song:
        raise ValueError(f"Song not found: {song_id}")

    prev = song.latest_revision
    revision = SongRevision(
        song_id=song_id,
        lyrics=lyrics if lyrics is not None else (prev.lyrics if prev else ""),
        prompt=prompt if prompt is not None else (prev.prompt if prev else ""),
        bpm=bpm if bpm is not None else (prev.bpm if prev else 0),
        duration=duration if duration is not None else (prev.duration if prev else 180),
        key=key if key is not None else (prev.key if prev else ""),
    )
    session.add(revision)
    session.flush()
    return revision


def song_to_dict(song: Song) -> dict:
    """Serialize a Song with its latest revision."""
    rev = song.latest_revision
    return {
        "id": song.id,
        "title": song.title,
        "album_id": song.album_id,
        "track_number": song.track_number,
        "language": song.language,
        "lyrics": rev.lyrics if rev else "",
        "prompt": rev.prompt if rev else "",
        "bpm": rev.bpm if rev else 0,
        "duration": rev.duration if rev else 180,
        "key": rev.key if rev else "",
        "revision_count": len(song.revisions),
        "version_count": len(song.versions),
        "created_at": song.created_at.isoformat() if song.created_at else None,
    }


def album_to_dict(album: Album) -> dict:
    """Serialize an Album to a dict for the API response."""
    return {
        "id": album.id,
        "title": album.title,
        "artist": album.artist,
        "subtitle": album.subtitle,
        "year": album.year,
        "colors": album.colors,
        "song_count": len(album.songs) if album.songs else 0,
    }
