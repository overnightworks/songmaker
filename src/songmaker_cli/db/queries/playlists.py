"""Query functions for playlists — CRUD, entries, sharing."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session, joinedload

from songmaker_cli.db.models import (
    Album,
    Generation,
    Playlist,
    PlaylistEntry,
    Song,
)
from songmaker_cli.db.queries.sharing import disable_sharing, enable_sharing

log = logging.getLogger(__name__)


def list_playlists(session: Session, user_id: str) -> list[Playlist]:
    return (
        session.query(Playlist)
        .options(joinedload(Playlist.entries))
        .filter_by(created_by=user_id)
        .order_by(Playlist.title)
        .all()
    )


def get_playlist(session: Session, playlist_id: str) -> Playlist | None:
    return (
        session.query(Playlist)
        .options(
            joinedload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.song)
            .joinedload(Song.album),
        )
        .filter_by(id=playlist_id)
        .first()
    )


def create_playlist(session: Session, title: str, user_id: str) -> Playlist:
    playlist = Playlist(title=title, created_by=user_id)
    session.add(playlist)
    session.flush()
    log.info("Created playlist '%s' (id=%s, owner=%s)", title, playlist.id, user_id)
    return playlist


def delete_playlist(session: Session, playlist_id: str) -> None:
    playlist = session.query(Playlist).filter_by(id=playlist_id).first()
    if not playlist:
        raise ValueError(f"Playlist not found: {playlist_id}")
    session.delete(playlist)
    session.flush()
    log.info("Deleted playlist %s", playlist_id)


def update_playlist(session: Session, playlist_id: str, title: str) -> Playlist:
    playlist = session.query(Playlist).filter_by(id=playlist_id).first()
    if not playlist:
        raise ValueError(f"Playlist not found: {playlist_id}")
    playlist.title = title
    session.flush()
    return playlist


def _next_position(session: Session, playlist_id: str) -> int:
    max_pos = (
        session.query(PlaylistEntry.position)
        .filter_by(playlist_id=playlist_id)
        .order_by(PlaylistEntry.position.desc())
        .first()
    )
    return (max_pos[0] + 1) if max_pos else 0


def add_generation_to_playlist(
    session: Session, playlist_id: str, generation_id: str,
) -> PlaylistEntry:
    gen = session.query(Generation).filter_by(id=generation_id).first()
    if not gen:
        raise ValueError(f"Generation not found: {generation_id}")
    position = _next_position(session, playlist_id)
    entry = PlaylistEntry(
        playlist_id=playlist_id, generation_id=generation_id, position=position,
    )
    session.add(entry)
    gen.is_kept = True
    session.flush()
    return entry


def add_song_to_playlist(
    session: Session, playlist_id: str, song_id: str,
) -> PlaylistEntry | None:
    song = (
        session.query(Song)
        .options(joinedload(Song.generations))
        .filter_by(id=song_id)
        .first()
    )
    if not song:
        raise ValueError(f"Song not found: {song_id}")
    picked = next((g for g in song.generations if g.is_picked), None)
    if not picked:
        return None
    return add_generation_to_playlist(session, playlist_id, picked.id)


def add_album_to_playlist(
    session: Session, playlist_id: str, album_id: str,
) -> list[PlaylistEntry]:
    album = (
        session.query(Album)
        .options(
            joinedload(Album.songs)
            .joinedload(Song.generations),
        )
        .filter_by(id=album_id)
        .first()
    )
    if not album:
        raise ValueError(f"Album not found: {album_id}")
    entries: list[PlaylistEntry] = []
    for song in sorted(album.songs, key=lambda s: s.track_number):
        picked = next((g for g in song.generations if g.is_picked), None)
        if picked:
            entry = add_generation_to_playlist(session, playlist_id, picked.id)
            entries.append(entry)
    return entries


def remove_from_playlist(
    session: Session, playlist_id: str, entry_id: str,
) -> None:
    entry = (
        session.query(PlaylistEntry)
        .filter_by(id=entry_id, playlist_id=playlist_id)
        .first()
    )
    if not entry:
        raise ValueError(f"Playlist entry not found: {entry_id}")
    removed_pos = entry.position
    session.delete(entry)
    session.query(PlaylistEntry).filter(
        PlaylistEntry.playlist_id == playlist_id,
        PlaylistEntry.position > removed_pos,
    ).update({"position": PlaylistEntry.position - 1})
    session.flush()


def reorder_playlist_entry(
    session: Session, playlist_id: str, entry_id: str, new_position: int,
) -> None:
    entry = (
        session.query(PlaylistEntry)
        .filter_by(id=entry_id, playlist_id=playlist_id)
        .first()
    )
    if not entry:
        raise ValueError(f"Playlist entry not found: {entry_id}")

    old_pos = entry.position
    if old_pos == new_position:
        return

    if new_position < old_pos:
        session.query(PlaylistEntry).filter(
            PlaylistEntry.playlist_id == playlist_id,
            PlaylistEntry.position >= new_position,
            PlaylistEntry.position < old_pos,
        ).update({"position": PlaylistEntry.position + 1})
    else:
        session.query(PlaylistEntry).filter(
            PlaylistEntry.playlist_id == playlist_id,
            PlaylistEntry.position > old_pos,
            PlaylistEntry.position <= new_position,
        ).update({"position": PlaylistEntry.position - 1})

    entry.position = new_position
    session.flush()


def get_playlist_by_slug(session: Session, slug: str) -> Playlist | None:
    return (
        session.query(Playlist)
        .options(
            joinedload(Playlist.entries)
            .joinedload(PlaylistEntry.generation)
            .joinedload(Generation.song)
            .joinedload(Song.album),
        )
        .filter_by(share_slug=slug, is_shared=True)
        .first()
    )


def enable_playlist_sharing(session: Session, playlist_id: str) -> Playlist:
    return enable_sharing(session, Playlist, playlist_id)


def disable_playlist_sharing(session: Session, playlist_id: str) -> Playlist:
    return disable_sharing(session, Playlist, playlist_id)
