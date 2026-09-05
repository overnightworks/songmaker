"""Library index search and browse response models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field

from songmaker_cli.api_models.songs import AlbumCoverUrls, AlbumResponse, SongSummaryResponse
from songmaker_cli.constants import (
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_GENERATION,
    LIBRARY_ITEM_PLAYLIST,
    LIBRARY_ITEM_SONG,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
    SHARE_PUBLIC_PATH_ALBUM,
    SHARE_PUBLIC_PATH_GENERATION,
    SHARE_PUBLIC_PATH_PLAYLIST,
    SHARE_PUBLIC_PATH_SONG,
)

if TYPE_CHECKING:
    from songmaker_cli.db.models import Album, Generation, Playlist, Song
    from songmaker_cli.db.queries.songs import ContinueCandidate

LibrarySort = Literal[
    "newest",
    "oldest",
    "title",
]

LIBRARY_SORT_VALUES: tuple[LibrarySort, ...] = (
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
)


class LibraryAlbumHit(BaseModel):
    type: Literal["album"] = LIBRARY_ITEM_ALBUM
    album: AlbumResponse

    @classmethod
    def from_orm(cls, album: Album, *, song_count: int, picked_count: int = 0) -> LibraryAlbumHit:
        return cls(
            type=LIBRARY_ITEM_ALBUM,
            album=AlbumResponse.from_orm(
                album, song_count=song_count, picked_count=picked_count,
            ),
        )


class LibrarySongHit(BaseModel):
    type: Literal["song"] = LIBRARY_ITEM_SONG
    song: SongSummaryResponse
    album_id: str
    album_title: str

    @classmethod
    def from_orm(cls, song: Song) -> LibrarySongHit:
        if song.album is None:
            raise ValueError(f"Song {song.id} has no album")
        # search_library() eager-loads Song.generations for every hit
        # (_SONG_LIST_OPTIONS), so this costs no extra query.
        return cls(
            type=LIBRARY_ITEM_SONG,
            song=SongSummaryResponse.from_orm(song, generation_count=len(song.generations)),
            album_id=song.album_id,
            album_title=song.album.title,
        )


LibrarySearchHit = Annotated[
    LibraryAlbumHit | LibrarySongHit,
    Field(discriminator="type"),
]


class LibrarySearchResponse(BaseModel):
    items: list[LibrarySearchHit]
    next_cursor: str | None
    has_more: bool

    @classmethod
    def from_orm(
        cls,
        hits: list[Album | Song],
        *,
        has_more: bool,
        next_cursor: str | None,
        song_counts: dict[str, int],
        picked_counts: dict[str, int] | None = None,
    ) -> LibrarySearchResponse:
        from songmaker_cli.db.models import Album as AlbumModel

        picked = picked_counts or {}
        songs = song_counts
        items: list[LibraryAlbumHit | LibrarySongHit] = []
        for hit in hits:
            if isinstance(hit, AlbumModel):
                items.append(
                    LibraryAlbumHit.from_orm(
                        hit,
                        song_count=songs.get(hit.id, 0),
                        picked_count=picked.get(hit.id, 0),
                    ),
                )
            else:
                items.append(LibrarySongHit.from_orm(hit))
        return cls(items=items, next_cursor=next_cursor, has_more=has_more)


class LibraryContinueItem(BaseModel):
    """A compact, tagged candidate for the Library Continue row."""

    type: Literal["album", "song"]
    id: str
    title: str
    cover: AlbumCoverUrls | None = None
    album_id: str | None = None
    album_title: str | None = None

    @classmethod
    def from_orm(cls, item: Album | Song) -> LibraryContinueItem:
        from songmaker_cli.api_models.songs import album_cover_urls, song_cover_urls
        from songmaker_cli.db.models import Album as AlbumModel

        if isinstance(item, AlbumModel):
            return cls(
                type=LIBRARY_ITEM_ALBUM,
                id=item.id,
                title=item.title,
                cover=album_cover_urls(item.id, item.cover_key) if item.cover_key else None,
            )
        if item.album is None:
            raise ValueError(f"Song {item.id} has no album")
        return cls(
            type=LIBRARY_ITEM_SONG,
            id=item.id,
            title=item.title,
            cover=song_cover_urls(item.id, item.cover_key) if item.cover_key else None,
            album_id=item.album_id,
            album_title=item.album.title,
        )


class LibraryContinueResponse(BaseModel):
    items: list[LibraryContinueItem]

    @classmethod
    def from_orm(cls, candidates: list[ContinueCandidate]) -> LibraryContinueResponse:
        return cls(
            items=[LibraryContinueItem.from_orm(candidate.item) for candidate in candidates],
        )


ShareInventoryType = Literal[
    "album",
    "song",
    "generation",
    "playlist",
]


class ShareInventoryItem(BaseModel):
    type: ShareInventoryType
    id: str
    title: str
    share_slug: str
    created_at: str
    public_path: str
    album_id: str | None = None
    album_title: str | None = None
    song_id: str | None = None
    song_title: str | None = None
    generation_number: int | None = None
    is_archived: bool | None = None

    @classmethod
    def from_orm(cls, entity: Album | Song | Generation | Playlist) -> ShareInventoryItem:
        from songmaker_cli.db.models import Album as AlbumModel
        from songmaker_cli.db.models import Generation as GenerationModel
        from songmaker_cli.db.models import Playlist as PlaylistModel
        from songmaker_cli.db.models import Song as SongModel

        if isinstance(entity, AlbumModel):
            return cls._from_album(entity)
        if isinstance(entity, SongModel):
            return cls._from_song(entity)
        if isinstance(entity, GenerationModel):
            return cls._from_generation(entity)
        if isinstance(entity, PlaylistModel):
            return cls._from_playlist(entity)
        raise TypeError(f"Unsupported share inventory entity: {type(entity).__name__}")

    @classmethod
    def _from_album(cls, album: Album) -> ShareInventoryItem:
        slug = _require_share_slug(album)
        return cls(
            type=LIBRARY_ITEM_ALBUM,
            id=album.id,
            title=album.title,
            share_slug=slug,
            created_at=album.created_at.isoformat(),
            public_path=SHARE_PUBLIC_PATH_ALBUM.format(slug=slug),
        )

    @classmethod
    def _from_song(cls, song: Song) -> ShareInventoryItem:
        if song.album is None:
            raise ValueError(f"Song {song.id} has no album")
        slug = _require_share_slug(song)
        return cls(
            type=LIBRARY_ITEM_SONG,
            id=song.id,
            title=song.title,
            share_slug=slug,
            created_at=song.created_at.isoformat(),
            public_path=SHARE_PUBLIC_PATH_SONG.format(slug=slug),
            album_id=song.album_id,
            album_title=song.album.title,
        )

    @classmethod
    def _from_generation(cls, generation: Generation) -> ShareInventoryItem:
        song = generation.song
        if song is None:
            raise ValueError(f"Generation {generation.id} has no song")
        slug = _require_share_slug(generation)
        return cls(
            type=LIBRARY_ITEM_GENERATION,
            id=generation.id,
            title=song.title,
            share_slug=slug,
            created_at=generation.created_at.isoformat(),
            public_path=SHARE_PUBLIC_PATH_GENERATION.format(slug=slug),
            song_id=generation.song_id,
            song_title=song.title,
            generation_number=generation.generation_number,
            is_archived=generation.is_archived,
        )

    @classmethod
    def _from_playlist(cls, playlist: Playlist) -> ShareInventoryItem:
        slug = _require_share_slug(playlist)
        return cls(
            type=LIBRARY_ITEM_PLAYLIST,
            id=playlist.id,
            title=playlist.title,
            share_slug=slug,
            created_at=playlist.created_at.isoformat(),
            public_path=SHARE_PUBLIC_PATH_PLAYLIST.format(slug=slug),
        )


def _require_share_slug(entity: Album | Song | Generation | Playlist) -> str:
    slug = entity.share_slug
    if not slug:
        raise ValueError(f"{type(entity).__name__} {entity.id} has no share slug")
    return slug
