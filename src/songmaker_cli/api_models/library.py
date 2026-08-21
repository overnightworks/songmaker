"""Library index search and browse response models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field

from songmaker_cli.api_models.songs import AlbumResponse, SongSummaryResponse
from songmaker_cli.constants import (
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
)

if TYPE_CHECKING:
    from songmaker_cli.db.models import Album, Song

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
    def from_orm(cls, album: Album) -> LibraryAlbumHit:
        return cls(type=LIBRARY_ITEM_ALBUM, album=AlbumResponse.from_orm(album))


class LibrarySongHit(BaseModel):
    type: Literal["song"] = LIBRARY_ITEM_SONG
    song: SongSummaryResponse
    album_id: str
    album_title: str

    @classmethod
    def from_orm(cls, song: Song) -> LibrarySongHit:
        if song.album is None:
            raise ValueError(f"Song {song.id} has no album")
        return cls(
            type=LIBRARY_ITEM_SONG,
            song=SongSummaryResponse.from_orm(song),
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
    ) -> LibrarySearchResponse:
        from songmaker_cli.db.models import Album as AlbumModel

        items: list[LibraryAlbumHit | LibrarySongHit] = []
        for hit in hits:
            if isinstance(hit, AlbumModel):
                items.append(LibraryAlbumHit.from_orm(hit))
            else:
                items.append(LibrarySongHit.from_orm(hit))
        return cls(items=items, next_cursor=next_cursor, has_more=has_more)
