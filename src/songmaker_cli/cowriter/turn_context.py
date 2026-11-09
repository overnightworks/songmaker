"""What the co-writer sees of a person's songs, albums, takes and notes in one turn."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.api_helpers import (
    check_album_access,
    check_generation_access,
    check_song_access,
    owner_filter,
)
from songmaker_cli.api_models import ChatTurnV2Request
from songmaker_cli.api_models.songs import score_values
from songmaker_cli.constants import (
    CURRENT_SONG_FRESHNESS_NOTE,
    TURN_BLOCK_ALBUM_NOTES,
    TURN_BLOCK_CURRENT_SONG,
    TURN_BLOCK_CURRENT_TAKE,
    TURN_BLOCK_MENTIONED_ALBUM,
    TURN_BLOCK_MENTIONED_SONGS,
    TURN_BLOCK_MENTIONED_VERSIONS,
    TURN_BLOCK_NO_TAKE,
    TURN_BLOCK_SONG_MEMORY,
    TURN_BLOCK_USER_MEMORY,
)
from songmaker_cli.db.models import Generation, Song
from songmaker_cli.db.queries.albums import get_album
from songmaker_cli.db.queries.memory import (
    get_album_memory,
    get_song_memory,
    get_user_memory,
)
from songmaker_cli.db.queries.sharing import is_playable_take, presented_take
from songmaker_cli.db.queries.songs import list_songs
from songmaker_cli.db.queries.versions import get_version


@dataclass(frozen=True)
class TurnContextBlock:
    name: str
    body: str
    preface: str | None = None

    def render(self) -> str:
        tagged = f"<{self.name}>\n{self.body}\n</{self.name}>"
        if self.preface is None:
            return tagged
        return f"{self.preface}\n{tagged}"


@dataclass(frozen=True)
class TurnContextEnvelope:
    blocks: tuple[TurnContextBlock, ...]

    def wrap_user_message(self, message: str) -> str:
        parts = [block.render() for block in self.blocks]
        parts.append(message)
        return "\n\n".join(parts)

    def names(self) -> list[str]:
        return [block.name for block in self.blocks]


def _format_current_song(song) -> str:
    parts = [
        f"id: {song.id}",
        f"title: {song.title}",
        f"album: {song.album.title if song.album else ''}",
    ]
    v = song.latest_version
    if v:
        if v.prompt:
            parts.append(f"style: {v.prompt}")
        if v.key_scale:
            parts.append(f"key: {v.key_scale}")
        if v.bpm:
            parts.append(f"bpm: {v.bpm}")
        if v.audio_duration:
            parts.append(f"duration: {v.audio_duration}s")
        if v.lyrics:
            parts.append(f"lyrics:\n{v.lyrics}")
    return "\n".join(parts)


def compose_turn_context(
    *,
    current_song: Song | None,
    user_memory_body: str,
    song_memory_body: str | None,
    album_notes_body: str | None,
    extra_blocks: Sequence[TurnContextBlock] = (),
) -> TurnContextEnvelope:
    """Assemble the provider-neutral turn envelope.

    Current song, memory scopes, and later mention/take blocks are wrapped
    here once. Providers must pass the result through unchanged.
    """
    blocks: list[TurnContextBlock] = []
    if current_song is not None:
        blocks.append(
            TurnContextBlock(
                TURN_BLOCK_CURRENT_SONG,
                _format_current_song(current_song),
                preface=CURRENT_SONG_FRESHNESS_NOTE,
            )
        )
    blocks.append(TurnContextBlock(TURN_BLOCK_USER_MEMORY, user_memory_body))
    if current_song is not None:
        blocks.append(
            TurnContextBlock(
                TURN_BLOCK_SONG_MEMORY,
                song_memory_body or "",
            )
        )
        if album_notes_body:
            blocks.append(
                TurnContextBlock(
                    TURN_BLOCK_ALBUM_NOTES,
                    album_notes_body,
                )
            )
    blocks.extend(extra_blocks)
    return TurnContextEnvelope(tuple(blocks))


def load_memory_for_turn(
    session: Session,
    user_id: str,
    current_song: Song | None,
) -> tuple[str, str | None, str | None]:
    user_row = get_user_memory(session, user_id)
    user_body = user_row.body if user_row else ""
    if current_song is None:
        return user_body, None, None
    song_row = get_song_memory(session, current_song.id)
    song_body = song_row.body if song_row else ""
    album_row = get_album_memory(session, current_song.album_id)
    album_body = album_row.body if album_row and album_row.body else None
    return user_body, song_body, album_body


def _unique_ids(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _format_version(version, song: Song) -> str:
    parts = [
        f"id: {version.id}",
        f"song_id: {song.id}",
        f"song_title: {song.title}",
        f"version_number: {version.version_number}",
    ]
    if version.prompt:
        parts.append(f"style: {version.prompt}")
    if version.key_scale:
        parts.append(f"key: {version.key_scale}")
    if version.bpm:
        parts.append(f"bpm: {version.bpm}")
    if version.audio_duration:
        parts.append(f"duration: {version.audio_duration}s")
    if version.lyrics:
        parts.append(f"lyrics:\n{version.lyrics}")
    return "\n".join(parts)


def resolve_mention_blocks(
    session: Session,
    user: AuthenticatedUser,
    current_song: Song | None,
    mentioned_song_ids: list[str],
    mentioned_version_ids: list[str],
    mentioned_album_id: str | None,
) -> list[TurnContextBlock]:
    """Load picker-selected mention targets from the DB.

    Unknown, foreign, or unrelated IDs 404 the whole turn. The client
    never supplies lyrics or other raw context as the source of truth.
    """
    blocks = _mentioned_song_blocks(session, user, current_song, mentioned_song_ids)
    album_block = _mentioned_album_block(session, user, current_song, mentioned_album_id)
    version_block = _mentioned_version_block(session, current_song, mentioned_version_ids)
    return [block for block in (*blocks, album_block, version_block) if block is not None]


def _mentioned_song_blocks(
    session: Session,
    user: AuthenticatedUser,
    current_song: Song | None,
    mentioned_song_ids: list[str],
) -> list[TurnContextBlock]:
    current_id = current_song.id if current_song is not None else None
    songs = [
        check_song_access(session, song_id, user)
        for song_id in _unique_ids(mentioned_song_ids)
        if song_id != current_id
    ]
    if not songs:
        return []
    body = "\n\n".join(_format_current_song(song) for song in songs)
    return [TurnContextBlock(TURN_BLOCK_MENTIONED_SONGS, body)]


def _mentioned_album_block(
    session: Session,
    user: AuthenticatedUser,
    current_song: Song | None,
    mentioned_album_id: str | None,
) -> TurnContextBlock | None:
    if mentioned_album_id is None:
        return None
    if current_song is None or mentioned_album_id != current_song.album_id:
        raise HTTPException(404, "Album not found")
    album = get_album(session, mentioned_album_id)
    check_album_access(album, user)
    tracks = list_songs(
        session,
        album_id=album.id,
        user_id=owner_filter(user),
        light=True,
    )
    body = f"id: {album.id}\ntitle: {album.title}\ntracks:\n"
    return TurnContextBlock(
        TURN_BLOCK_MENTIONED_ALBUM,
        body + "\n\n".join(_format_current_song(song) for song in tracks),
    )


def _mentioned_version_block(
    session: Session,
    current_song: Song | None,
    mentioned_version_ids: list[str],
) -> TurnContextBlock | None:
    version_ids = _unique_ids(mentioned_version_ids)
    if not version_ids:
        return None
    if current_song is None:
        raise HTTPException(404, "Version not found")
    versions = [get_version(session, version_id, current_song.id) for version_id in version_ids]
    if any(version is None for version in versions):
        raise HTTPException(404, "Version not found")
    body = "\n\n".join(_format_version(version, current_song) for version in versions)
    return TurnContextBlock(TURN_BLOCK_MENTIONED_VERSIONS, body)


def _format_take(generation: Generation) -> str:
    whisper = generation.whisper_text or ""
    parts = [
        f"generation_id: {generation.id}",
        f"generation_number: {generation.generation_number}",
        f"whisper_text:\n{whisper}",
        f"is_picked: {str(generation.is_picked).lower()}",
        f"is_kept: {str(generation.is_kept).lower()}",
    ]
    score_lines = [
        f"{key}: {value}" for key, value in sorted(score_values(generation).items())
    ]
    if score_lines:
        parts.append("scores:\n" + "\n".join(score_lines))
    return "\n".join(parts)


def resolve_take_block(
    session: Session,
    user: AuthenticatedUser,
    current_song: Song | None,
    current_generation_id: str | None,
) -> TurnContextBlock | None:
    """Pick the relevant playable take for the open song.

    An explicit player id is used only when it is owned, belongs to the
    current song, and is playable. Otherwise the server falls back to the
    playable pick, then the newest playable take. Missing takes are a
    named empty state, never a silent substitute.
    """
    if current_generation_id is not None:
        generation = check_generation_access(session, current_generation_id, user)
        if current_song is None or generation.song_id != current_song.id:
            raise HTTPException(
                422,
                "Generation does not belong to the current song",
            )
        if not is_playable_take(generation):
            raise HTTPException(422, "Generation is not playable")
        return TurnContextBlock(TURN_BLOCK_CURRENT_TAKE, _format_take(generation))

    if current_song is None:
        return None
    playable = presented_take(current_song.generations)
    if playable is None:
        return TurnContextBlock(TURN_BLOCK_NO_TAKE, "no playable take")
    return TurnContextBlock(TURN_BLOCK_CURRENT_TAKE, _format_take(playable))


def load_turn_context(
    req: ChatTurnV2Request,
    user: AuthenticatedUser,
    session: Session,
) -> TurnContextEnvelope:
    current_song = (
        check_song_access(session, req.current_song_id, user)
        if req.current_song_id is not None
        else None
    )
    extra_blocks = resolve_mention_blocks(
        session,
        user,
        current_song,
        req.mentioned_song_ids,
        req.mentioned_version_ids,
        req.mentioned_album_id,
    )
    if take_block := resolve_take_block(session, user, current_song, req.current_generation_id):
        extra_blocks.append(take_block)
    user_memory_body, song_memory_body, album_notes_body = load_memory_for_turn(
        session,
        user.id,
        current_song,
    )
    return compose_turn_context(
        current_song=current_song,
        user_memory_body=user_memory_body,
        song_memory_body=song_memory_body,
        album_notes_body=album_notes_body,
        extra_blocks=extra_blocks,
    )
