"""Library index search and browse response models."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, Field

from songmaker_cli.api_models.playlists import playlist_mosaic_covers, uploaded_playlist_cover
from songmaker_cli.api_models.songs import (
    AlbumCoverUrls,
    AlbumResponse,
    SongSummaryResponse,
    album_cover_urls,
    song_cover_urls,
)
from songmaker_cli.constants import (
    LIBRARY_ITEM_ALBUM,
    LIBRARY_ITEM_SONG,
    LIBRARY_SORT_NEWEST,
    LIBRARY_SORT_OLDEST,
    LIBRARY_SORT_TITLE,
    SongWorkKind,
)

if TYPE_CHECKING:
    from songmaker_cli.db.models import Album, Song
    from songmaker_cli.db.queries.activity import PlaceListen, WorkedSong

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
    def from_orm(
        cls,
        album: Album,
        *,
        song_count: int,
        picked_count: int = 0,
        has_playable_take: bool = False,
    ) -> LibraryAlbumHit:
        return cls(
            type=LIBRARY_ITEM_ALBUM,
            album=AlbumResponse.from_orm(
                album,
                song_count=song_count,
                picked_count=picked_count,
                has_playable_take=has_playable_take,
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
        playable_album_ids: set[str] | None = None,
    ) -> LibrarySearchResponse:
        from songmaker_cli.db.models import Album as AlbumModel

        picked = picked_counts or {}
        playable = playable_album_ids or set()
        songs = song_counts
        items: list[LibraryAlbumHit | LibrarySongHit] = []
        for hit in hits:
            if isinstance(hit, AlbumModel):
                items.append(
                    LibraryAlbumHit.from_orm(
                        hit,
                        song_count=songs.get(hit.id, 0),
                        picked_count=picked.get(hit.id, 0),
                        has_playable_take=hit.id in playable,
                    ),
                )
            else:
                items.append(LibrarySongHit.from_orm(hit))
        return cls(items=items, next_cursor=next_cursor, has_more=has_more)


class LibraryListenItem(BaseModel):
    """An album or playlist in Home's Listen, with the song the musician last heard there."""

    type: Literal["album", "playlist"]
    id: str
    title: str
    cover: AlbumCoverUrls | None = None
    album_covers: list[AlbumCoverUrls] = Field(default_factory=list)
    song_id: str | None = None
    song_title: str | None = None
    song_number: int | None = None
    entry_id: str | None = None
    played_at: str

    @classmethod
    def from_orm(cls, listen: PlaceListen) -> LibraryListenItem:
        from songmaker_cli.db.models import Album as AlbumModel

        place = listen.place
        if isinstance(place, AlbumModel):
            cover = album_cover_urls(place.id, place.cover_key) if place.cover_key else None
            album_covers: list[AlbumCoverUrls] = []
        else:
            cover = uploaded_playlist_cover(place)
            album_covers = playlist_mosaic_covers(place)
        song = listen.song
        return cls(
            type=listen.place_type,
            id=place.id,
            title=place.title,
            cover=cover,
            album_covers=album_covers,
            song_id=song.id if song else None,
            song_title=song.title if song else None,
            song_number=listen.song_number,
            entry_id=listen.entry_id,
            played_at=listen.played_at.isoformat(),
        )


class LibraryListenResponse(BaseModel):
    items: list[LibraryListenItem]

    @classmethod
    def from_orm(cls, listens: list[PlaceListen]) -> LibraryListenResponse:
        return cls(items=[LibraryListenItem.from_orm(listen) for listen in listens])


class LibraryWriteItem(BaseModel):
    """A song in Home's Write, with the musician's newest kind of work on it."""

    song_id: str
    song_title: str
    album_id: str
    album_title: str
    cover: AlbumCoverUrls | None = None
    album_cover: AlbumCoverUrls | None = None
    work: SongWorkKind
    worked_at: str

    @classmethod
    def from_orm(cls, worked: WorkedSong) -> LibraryWriteItem:
        song = worked.song
        album = song.album
        return cls(
            song_id=song.id,
            song_title=song.title,
            album_id=album.id,
            album_title=album.title,
            cover=song_cover_urls(song.id, song.cover_key) if song.cover_key else None,
            album_cover=album_cover_urls(album.id, album.cover_key) if album.cover_key else None,
            work=worked.work,
            worked_at=worked.worked_at.isoformat(),
        )


class LibraryWriteResponse(BaseModel):
    items: list[LibraryWriteItem]

    @classmethod
    def from_orm(cls, worked_songs: list[WorkedSong]) -> LibraryWriteResponse:
        return cls(items=[LibraryWriteItem.from_orm(worked) for worked in worked_songs])
