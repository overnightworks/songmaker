"""Co-writer tool bodies and dispatch, called without any transport.

The ``tools.tool_*`` functions are driven directly with a DB session and an
``AuthenticatedUser``; ``execute_cowriter_tool`` is the shared entry point.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.orm import Session
from webauth.ports import AuthenticatedUser

from songmaker_cli.agent.tools import cowriter_hand_tools
from songmaker_cli.constants import (
    GET_SONG_ONLY_FOR_OTHER_SONGS,
    AuditAction,
    ResourceType,
    SongWorkKind,
)
from songmaker_cli.cowriter.tools import COWRITER_TOOLS, execute_cowriter_tool
from songmaker_cli.db.models import (
    Album,
    AuditLog,
    Generation,
    Score,
    Song,
    User,
    UserSongWork,
    Version,
)
from songmaker_cli.db.queries.auth import create_session
from songmaker_cli.mcp_server import auth, tools


@pytest.fixture
def db_session(tmp_path: Path, pg_factory) -> Session:
    session = pg_factory()
    yield session
    session.close()


def _seed_owned_song(session: Session) -> tuple[str, str, str, str, str]:
    """Create owner + non-owner + album + song. Returns ids."""
    owner = User(id="u1", username="alice", role="user")
    stranger = User(id="u2", username="bob", role="user")
    session.add_all([owner, stranger])
    session.flush()

    album = Album(id="album1", title="Test Album", artist="Alice", created_by="u1")
    session.add(album)

    song = Song(id="song1", title="First Song", album_id="album1", track_number=1)
    session.add(song)

    version = Version(
        id="v1", song_id="song1", version_number=1,
        lyrics="verse one", prompt="rock", bpm=120, key_scale="Am",
        audio_duration=180,
    )
    session.add(version)
    session.commit()
    return owner.id, stranger.id, album.id, song.id, version.id


def _owner(session: Session, user_id: str) -> AuthenticatedUser:
    return auth.load_user(session, user_id)


# ── auth.py ───────────────────────────────────────────────────────────

def test_load_user_not_found(db_session: Session):
    with pytest.raises(auth.ToolUserNotFoundError):
        auth.load_user(db_session, "nope")


# ── Read tools ────────────────────────────────────────────────────────


def test_list_albums_scoped_to_owner(db_session: Session):
    owner_id, stranger_id, _, _, _ = _seed_owned_song(db_session)
    db_session.add(Album(id="other", title="Other", artist="Bob", created_by=stranger_id))
    db_session.commit()

    owner = _owner(db_session, owner_id)
    stranger = _owner(db_session, stranger_id)

    owner_albums = tools.tool_list_albums(db_session, owner)
    assert [a.id for a in owner_albums] == ["album1"]
    assert owner_albums[0].song_count == 1

    stranger_albums = tools.tool_list_albums(db_session, stranger)
    assert [a.id for a in stranger_albums] == ["other"]


def test_list_songs_without_album(db_session: Session):
    owner_id, _, _, _, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    songs = tools.tool_list_songs(db_session, owner)
    assert [s.id for s in songs] == ["song1"]
    assert songs[0].album_title == "Test Album"
    assert songs[0].version_count == 1


@pytest.mark.parametrize(
    ("mp3_path", "is_archived", "has_playable_pick"),
    [("p/g1.mp3", False, True), ("", False, False), ("p/g1.mp3", True, False)],
    ids=["playable", "empty-audio-path", "archived"],
)
def test_list_songs_reports_a_pick_only_when_it_is_playable(
    db_session: Session, mp3_path: str, is_archived: bool, has_playable_pick: bool,
):
    owner_id, _, _, song_id, version_id = _seed_owned_song(db_session)
    db_session.add(Generation(
        id="gen1", song_id=song_id, version_id=version_id, generation_number=1,
        mp3_path=mp3_path, seed=1, is_picked=True, is_archived=is_archived,
    ))
    db_session.commit()
    songs = tools.tool_list_songs(db_session, _owner(db_session, owner_id))
    assert songs[0].has_picked_generation is has_playable_pick


def test_list_songs_filtered_by_album(db_session: Session):
    owner_id, _, album_id, _, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    songs = tools.tool_list_songs(db_session, owner, album_id=album_id)
    assert [s.id for s in songs] == ["song1"]


def test_list_songs_rejects_other_users_album(db_session: Session):
    owner_id, stranger_id, album_id, _, _ = _seed_owned_song(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_list_songs(db_session, stranger, album_id=album_id)


def test_search_songs_matches_title(db_session: Session):
    owner_id, _, _, _, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    hit = tools.tool_search_songs(db_session, owner, query="FIRST")
    miss = tools.tool_search_songs(db_session, owner, query="nope")
    assert [s.id for s in hit] == ["song1"]
    assert miss == []


def test_search_songs_rejects_empty(db_session: Session):
    owner_id, _, _, _, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_search_songs(db_session, owner, query="   ")


def test_search_songs_limit_validated(db_session: Session):
    owner_id, _, _, _, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_search_songs(db_session, owner, query="a", limit=0)
    with pytest.raises(tools.MCPToolError):
        tools.tool_search_songs(
            db_session, owner, query="a", limit=tools.MAX_SEARCH_RESULTS + 1,
        )


def test_get_song_returns_current_draft(db_session: Session):
    owner_id, _, _, song_id, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    detail = tools.tool_get_song(db_session, owner, song_id=song_id)
    assert detail.id == "song1"
    assert detail.current_lyrics == "verse one"
    assert detail.current_prompt == "rock"
    assert detail.current_bpm == 120
    assert detail.latest_version_id == "v1"
    assert detail.picked_generation_id is None


def test_get_song_blocks_other_user(db_session: Session):
    _, stranger_id, _, song_id, _ = _seed_owned_song(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_get_song(db_session, stranger, song_id=song_id)


def test_get_version_and_not_found(db_session: Session):
    owner_id, _, _, song_id, version_id = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    v = tools.tool_get_version(db_session, owner, song_id=song_id, version_id=version_id)
    assert v.lyrics == "verse one"
    with pytest.raises(tools.MCPToolError):
        tools.tool_get_version(db_session, owner, song_id=song_id, version_id="bogus")


def test_get_version_blocks_other_user(db_session: Session):
    _, stranger_id, _, song_id, version_id = _seed_owned_song(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_get_version(
            db_session, stranger, song_id=song_id, version_id=version_id,
        )


def _batch_scores() -> dict:
    return {
        "text_accuracy": 86.2,
        "lyrical_coherence": 8,
        "lyrical_summary": "Coherent verses.",
        "bpm_detected": 96.0,
    }


def _seed_take(db_session: Session, batch_value: dict | None):
    owner_id, _, _, song_id, version_id = _seed_owned_song(db_session)
    db_session.add(Generation(
        id="gen1", song_id=song_id, version_id=version_id, generation_number=1,
        mp3_path="p/g1.mp3", seed=42, is_picked=True, is_kept=True,
    ))
    if batch_value is not None:
        db_session.add(
            Score(id="sc1", generation_id="gen1", scorer="batch", value=batch_value),
        )
    db_session.commit()
    return _owner(db_session, owner_id)


def test_get_generation_returns_stored_batch_keys_flat(db_session: Session):
    owner = _seed_take(db_session, _batch_scores())
    detail = tools.tool_get_generation(db_session, owner, generation_id="gen1")
    assert detail.is_picked is True
    assert detail.scores == _batch_scores()
    assert isinstance(detail.scores["lyrical_coherence"], int)


def test_cowriter_get_generation_keeps_integer_score_in_json(db_session: Session):
    owner = _seed_take(db_session, _batch_scores())
    outcome = execute_cowriter_tool(
        db_session, owner, "get_generation", {"generation_id": "gen1"},
        session_id=None,
    )
    assert not outcome.is_error
    shown = json.loads(outcome.content)["scores"]["lyrical_coherence"]
    assert shown == 8
    assert type(shown) is int


def test_get_generation_without_score_row_has_no_scores(db_session: Session):
    owner = _seed_take(db_session, None)
    detail = tools.tool_get_generation(db_session, owner, generation_id="gen1")
    assert detail.scores == {}


def test_get_generation_blocks_other_user(db_session: Session):
    owner_id, stranger_id, _, song_id, version_id = _seed_owned_song(db_session)
    db_session.add(Generation(
        id="gen1", song_id=song_id, version_id=version_id, generation_number=1,
        mp3_path="p/g1.mp3",
    ))
    db_session.commit()

    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_get_generation(db_session, stranger, generation_id="gen1")


# ── Write tools ───────────────────────────────────────────────────────


def test_create_song_requires_access(db_session: Session):
    _, stranger_id, album_id, _, _ = _seed_owned_song(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_create_song(
            db_session, stranger, album_id=album_id, title="Sneak",
        )


def test_create_song_persists_and_returns_state(db_session: Session):
    owner_id, _, album_id, _, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_create_song(
        db_session, owner, album_id=album_id, title="Second Song",
        lyrics="hello", prompt="disco",
    )
    assert result.ok is True
    assert result.song.title == "Second Song"
    assert result.song.current_lyrics == "hello"
    assert result.song.current_prompt == "disco"
    stored = db_session.query(Song).filter_by(id=result.song_id).one()
    assert stored.track_number == 2  # seeded song took track 1
    assert stored.slug == "second-song"


def test_cowriter_created_song_stays_on_auto_after_a_lyrics_edit(db_session: Session):
    owner_id, _, album_id, _, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    created = tools.tool_create_song(db_session, owner, album_id=album_id, title="Auto")
    assert created.song.current_audio_duration == 0
    edited = tools.tool_update_song_lyrics(db_session, owner, song_id=created.song_id, lyrics="la")
    assert edited.song.current_audio_duration == 0


def test_create_song_dedupes_slug_against_sibling_in_same_album(db_session: Session):
    owner_id, _, album_id, _, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    tools.tool_create_song(db_session, owner, album_id=album_id, title="Twin")
    db_session.commit()
    result = tools.tool_create_song(db_session, owner, album_id=album_id, title="Twin")
    stored = db_session.query(Song).filter_by(id=result.song_id).one()
    assert stored.slug == "twin-2"


def test_update_lyrics_always_creates_a_new_version_and_preserves_existing_take(
    db_session: Session,
):
    owner_id, _, _, song_id, version_id = _seed_owned_song(db_session)
    db_session.add(Generation(
        id="gen1", song_id=song_id, version_id=version_id, generation_number=1,
        mp3_path="p/g1.mp3",
    ))
    db_session.commit()
    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_lyrics(
        db_session, owner, song_id=song_id, lyrics="brand new lyric",
    )
    assert result.song.current_lyrics == "brand new lyric"
    assert len(result.song.versions) == 2
    assert result.song.latest_version_id != version_id
    assert result.message == "Updated lyrics in v2"
    existing_take = db_session.query(Generation).filter_by(id="gen1").one()
    assert existing_take.version_id == version_id
    original_version = db_session.query(Version).filter_by(id=version_id).one()
    assert original_version.lyrics == "verse one"


def test_update_lyrics_creates_new_version_when_generated(db_session: Session):
    owner_id, _, _, song_id, version_id = _seed_owned_song(db_session)
    db_session.add(Generation(
        id="gen1", song_id=song_id, version_id=version_id, generation_number=1,
        mp3_path="p/g1.mp3",
    ))
    db_session.commit()

    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_lyrics(
        db_session, owner, song_id=song_id, lyrics="post-gen rewrite",
    )
    assert len(result.song.versions) == 2
    assert result.song.latest_version_id != version_id
    assert result.song.current_lyrics == "post-gen rewrite"


def test_update_prompt(db_session: Session):
    owner_id, _, _, song_id, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_prompt(
        db_session, owner, song_id=song_id, prompt="jazzy bossa",
    )
    assert result.song.current_prompt == "jazzy bossa"
    assert result.song.current_lyrics == "verse one"  # untouched


def test_update_style_requires_at_least_one_param(db_session: Session):
    owner_id, _, _, song_id, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_update_song_style(db_session, owner, song_id=song_id)


def test_update_style_applies_partial(db_session: Session):
    owner_id, _, _, song_id, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_style(
        db_session, owner, song_id=song_id, bpm=88, key_scale="F#m",
    )
    assert result.song.current_bpm == 88
    assert result.song.current_key_scale == "F#m"
    assert result.song.current_audio_duration == 180  # unchanged


def test_update_style_with_duration(db_session: Session):
    owner_id, _, _, song_id, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_style(
        db_session, owner, song_id=song_id, audio_duration=240,
    )
    assert result.song.current_audio_duration == 240
    assert "duration=240s" in result.message


def test_rename_song(db_session: Session):
    owner_id, _, _, song_id, version_id = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_rename_song(
        db_session, owner, song_id=song_id, title="Renamed Track",
    )
    assert result.song.title == "Renamed Track"
    stored = db_session.query(Song).filter_by(id=song_id).one()
    assert stored.slug == "renamed-track"
    assert len(stored.versions) == 2
    assert stored.latest_version.id != version_id
    assert result.message == "Renamed song to 'Renamed Track' in v2"


def test_rename_song_dedupes_slug_against_sibling_in_same_album(db_session: Session):
    owner_id, _, album_id, song_id, _ = _seed_owned_song(db_session)
    owner = _owner(db_session, owner_id)
    tools.tool_create_song(db_session, owner, album_id=album_id, title="Rival")
    db_session.commit()
    result = tools.tool_rename_song(db_session, owner, song_id=song_id, title="Rival")
    stored = db_session.query(Song).filter_by(id=result.song_id).one()
    assert stored.slug == "rival-2"


TITLE_WRITES = pytest.mark.parametrize(
    ("tool_name", "target"), [("create_song", "album_id"), ("rename_song", "song_id")])


def _co_writer_title_write(db_session: Session, tool_name: str, target: str, title: str):
    owner_id, _, album_id, song_id, _ = _seed_owned_song(db_session)
    arguments = {target: {"album_id": album_id, "song_id": song_id}[target], "title": title}
    return execute_cowriter_tool(
        db_session, _owner(db_session, owner_id), tool_name, arguments, session_id=None,
    )


@TITLE_WRITES
def test_co_writer_stores_the_stripped_title(db_session: Session, tool_name, target):
    outcome = _co_writer_title_write(db_session, tool_name, target, "  Night Drive ")

    assert not outcome.is_error
    assert db_session.query(Song).filter_by(title="Night Drive").one().slug == "night-drive"


@TITLE_WRITES
@pytest.mark.parametrize(
    "title", ["   ", "x" * (Song.__table__.c.title.type.length + 1)], ids=["blank", "overlong"],
)
def test_co_writer_refuses_unstorable_title_before_any_write(db_session, tool_name, target, title):
    owner_id, _, album_id, song_id, _ = _seed_owned_song(db_session)
    target_id = {"album_id": album_id, "song_id": song_id}[target]
    before = db_session.query(Song.id, Song.title, Song.slug).all()
    tool = getattr(tools, f"tool_{tool_name}")
    owner = _owner(db_session, owner_id)
    # The tool body runs outside the executor, whose rollback would hide an earlier write.
    with pytest.raises(tools.MCPToolError):
        tool(db_session, owner, **{target: target_id}, title=title)

    assert not db_session.new
    assert not db_session.dirty
    assert db_session.query(Song.id, Song.title, Song.slug).all() == before
    assert db_session.query(AuditLog).count() == 0


def test_write_tools_block_other_users(db_session: Session):
    _, stranger_id, _, song_id, _ = _seed_owned_song(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_update_song_lyrics(
            db_session, stranger, song_id=song_id, lyrics="hack",
        )
    with pytest.raises(tools.MCPToolError):
        tools.tool_update_song_prompt(
            db_session, stranger, song_id=song_id, prompt="hack",
        )
    with pytest.raises(tools.MCPToolError):
        tools.tool_update_song_style(
            db_session, stranger, song_id=song_id, bpm=100,
        )
    with pytest.raises(tools.MCPToolError):
        tools.tool_rename_song(
            db_session, stranger, song_id=song_id, title="hack",
        )
    assert db_session.query(UserSongWork).count() == 0


@pytest.mark.parametrize(
    ("tool", "arguments", "kind"),
    [
        (tools.tool_update_song_lyrics, {"lyrics": "new words"}, SongWorkKind.LYRICS),
        (tools.tool_update_song_prompt, {"prompt": "jazz"}, SongWorkKind.STYLE),
        (tools.tool_update_song_style, {"bpm": 90}, SongWorkKind.STYLE),
        (tools.tool_rename_song, {"title": "New Title"}, SongWorkKind.RENAMED),
    ],
    ids=["lyrics", "prompt", "style", "rename"],
)
@pytest.mark.parametrize("role", ["admin", "user"])
def test_co_writer_edits_record_the_editors_own_work_and_its_kind(
    db_session: Session, tool, arguments, kind, role,
):
    """1301-F2-WORK: owned edits retain the acting musician and work kind."""
    editor_id, _, _, song_id, _ = _seed_owned_song(db_session)
    db_session.get(User, editor_id).role = role
    db_session.commit()
    editor = _owner(db_session, editor_id)

    tool(db_session, editor, song_id=song_id, **arguments)

    work = db_session.query(UserSongWork).one()
    assert (work.user_id, work.song_id) == (editor_id, song_id)
    assert work.edited_at is not None
    assert work.edit_kind == kind
    assert work.played_at is None


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        (tools.tool_update_song_lyrics, {"lyrics": "verse one"}),
        (tools.tool_update_song_prompt, {"prompt": "rock"}),
        (tools.tool_update_song_style, {"bpm": 120, "key_scale": "Am"}),
        (tools.tool_rename_song, {"title": "First Song"}),
    ],
    ids=["lyrics", "prompt", "style", "rename"],
)
def test_co_writer_writes_that_change_nothing_record_no_work(
    db_session: Session, tool, arguments,
):
    owner_id, _, _, song_id, _ = _seed_owned_song(db_session)

    tool(db_session, _owner(db_session, owner_id), song_id=song_id, **arguments)

    assert db_session.query(UserSongWork).count() == 0


@pytest.mark.parametrize(
    ("tool_name", "arguments", "action", "resource_type", "resource"),
    [
        ("create_song", {"album_id": "album1", "title": "Fresh"},
         AuditAction.CREATE, ResourceType.SONG, "created"),
        ("update_song_lyrics", {"song_id": "song1", "lyrics": "new words"},
         AuditAction.UPDATE, ResourceType.SONG, "song1"),
        ("update_song_prompt", {"song_id": "song1", "prompt": "jazz"},
         AuditAction.UPDATE, ResourceType.SONG, "song1"),
        ("update_song_style", {"song_id": "song1", "bpm": 90},
         AuditAction.UPDATE, ResourceType.SONG, "song1"),
        ("rename_song", {"song_id": "song1", "title": "New Title"},
         AuditAction.UPDATE, ResourceType.SONG, "song1"),
        ("suggest_album_cover", {"album_id": "album1"},
         AuditAction.GENERATE, ResourceType.ALBUM, "album1"),
        ("save_coherence_verdict",
         {"generation_id": "gen1", "score": 7, "summary": "Holds together."},
         AuditAction.SCORE, ResourceType.GENERATION, "gen1"),
    ],
    ids=["create", "lyrics", "prompt", "style", "rename", "cover", "verdict"],
)
def test_co_writer_writes_leave_their_audit_row(
    db_session: Session, tool_name, arguments, action, resource_type, resource,
):
    owner = _seed_take(db_session, None)
    db_session.get(Generation, "gen1").whisper_text = "sung words"
    db_session.commit()

    asking = create_session(db_session, owner.id, datetime.now(timezone.utc) + timedelta(hours=1))
    db_session.commit()

    outcome = execute_cowriter_tool(db_session, owner, tool_name, arguments, session_id=asking.id)

    assert not outcome.is_error
    db_session.expire_all()
    entry = db_session.query(AuditLog).one()
    assert (entry.user_id, entry.action, entry.resource_type) == (
        owner.id, action, resource_type,
    )
    if resource == "created":
        resource = db_session.query(Song).filter_by(title="Fresh").one().id
    assert entry.resource_id == resource


@pytest.mark.parametrize("role", ["admin", "user"])
def test_co_writer_song_creation_records_the_creators_own_work(
    db_session: Session, role,
):
    """1301-F2-WORK: owned creation records the acting musician."""
    creator_id, _, album_id, _, _ = _seed_owned_song(db_session)
    db_session.get(User, creator_id).role = role
    db_session.commit()

    result = tools.tool_create_song(
        db_session, _owner(db_session, creator_id), album_id=album_id, title="Fresh",
    )

    work = db_session.query(UserSongWork).one()
    assert (work.user_id, work.song_id) == (creator_id, result.song_id)
    assert work.edited_at is not None
    assert work.edit_kind == SongWorkKind.CREATED


# ── End-to-end via MCPServer.call_tool ──────────────────────────────────


def test_every_co_writer_route_reads_the_same_get_song_rule(tmp_path: Path, pg_factory):
    catalog_descriptions = {tool.name: tool.description for tool in COWRITER_TOOLS}
    hand_descriptions = {
        hand_tool.declaration.name: hand_tool.declaration.description
        for hand_tool in cowriter_hand_tools(pg_factory)
    }
    assert GET_SONG_ONLY_FOR_OTHER_SONGS in catalog_descriptions["get_song"]
    assert hand_descriptions["get_song"] == catalog_descriptions["get_song"]
