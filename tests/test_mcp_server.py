"""Tests for the songmaker MCP server.

Most coverage comes from calling the pure ``tool_*`` functions
directly with a DB session + ``AuthenticatedUser``. A small end-to-end
suite drives the FastMCP server via ``call_tool()`` to exercise the
session/auth plumbing in ``server.py``.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Generation, Score, Song, User, Version
from songmaker_cli.mcp_server import auth, server, tools
from songmaker_cli.middleware.auth import AuthenticatedUser


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    factory = init_test_db(tmp_path / "mcp.db")
    session = factory()
    yield session
    session.close()


@pytest.fixture()
def db_factory(tmp_path: Path):
    return init_test_db(tmp_path / "mcp_e2e.db")


def _seed(session: Session) -> tuple[str, str, str, str, str]:
    """Create owner + non-owner + album + song. Returns ids."""
    owner = User(id="u1", username="alice", password_hash="x", role="user")
    stranger = User(id="u2", username="bob", password_hash="x", role="user")
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


def test_require_user_id_raises_when_missing(monkeypatch):
    monkeypatch.delenv(auth.USER_ID_ENV, raising=False)
    with pytest.raises(auth.MCPAuthError):
        auth.require_user_id()


def test_require_user_id_returns_value(monkeypatch):
    monkeypatch.setenv(auth.USER_ID_ENV, "u1")
    assert auth.require_user_id() == "u1"


def test_load_user_not_found(db_session: Session):
    with pytest.raises(auth.MCPAuthError):
        auth.load_user(db_session, "nope")


def test_load_user_deactivated(db_session: Session):
    db_session.add(
        User(id="u3", username="charlie", password_hash="x", role="user", is_active=False),
    )
    db_session.commit()
    with pytest.raises(auth.MCPAuthError):
        auth.load_user(db_session, "u3")


# ── Read tools ────────────────────────────────────────────────────────


def test_list_albums_scoped_to_owner(db_session: Session):
    owner_id, stranger_id, _, _, _ = _seed(db_session)
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
    owner_id, _, _, _, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    songs = tools.tool_list_songs(db_session, owner)
    assert [s.id for s in songs] == ["song1"]
    assert songs[0].album_title == "Test Album"
    assert songs[0].version_count == 1


def test_list_songs_filtered_by_album(db_session: Session):
    owner_id, _, album_id, _, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    songs = tools.tool_list_songs(db_session, owner, album_id=album_id)
    assert [s.id for s in songs] == ["song1"]


def test_list_songs_rejects_other_users_album(db_session: Session):
    owner_id, stranger_id, album_id, _, _ = _seed(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_list_songs(db_session, stranger, album_id=album_id)


def test_search_songs_matches_title(db_session: Session):
    owner_id, _, _, _, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    hit = tools.tool_search_songs(db_session, owner, query="FIRST")
    miss = tools.tool_search_songs(db_session, owner, query="nope")
    assert [s.id for s in hit] == ["song1"]
    assert miss == []


def test_search_songs_rejects_empty(db_session: Session):
    owner_id, _, _, _, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_search_songs(db_session, owner, query="   ")


def test_search_songs_limit_validated(db_session: Session):
    owner_id, _, _, _, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_search_songs(db_session, owner, query="a", limit=0)
    with pytest.raises(tools.MCPToolError):
        tools.tool_search_songs(
            db_session, owner, query="a", limit=tools.MAX_SEARCH_RESULTS + 1,
        )


def test_get_song_returns_current_draft(db_session: Session):
    owner_id, _, _, song_id, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    detail = tools.tool_get_song(db_session, owner, song_id=song_id)
    assert detail.id == "song1"
    assert detail.current_lyrics == "verse one"
    assert detail.current_prompt == "rock"
    assert detail.current_bpm == 120
    assert detail.latest_version_id == "v1"
    assert detail.picked_generation_id is None


def test_get_song_blocks_other_user(db_session: Session):
    _, stranger_id, _, song_id, _ = _seed(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_get_song(db_session, stranger, song_id=song_id)


def test_get_version_and_not_found(db_session: Session):
    owner_id, _, _, song_id, version_id = _seed(db_session)
    owner = _owner(db_session, owner_id)
    v = tools.tool_get_version(db_session, owner, song_id=song_id, version_id=version_id)
    assert v.lyrics == "verse one"
    with pytest.raises(tools.MCPToolError):
        tools.tool_get_version(db_session, owner, song_id=song_id, version_id="bogus")


def test_get_version_blocks_other_user(db_session: Session):
    _, stranger_id, _, song_id, version_id = _seed(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_get_version(
            db_session, stranger, song_id=song_id, version_id=version_id,
        )


def test_get_generation_returns_scores(db_session: Session):
    owner_id, _, _, song_id, version_id = _seed(db_session)
    gen = Generation(
        id="gen1", song_id=song_id, version_id=version_id, generation_number=1,
        mp3_path="p/g1.mp3", seed=42, is_picked=True, is_kept=True,
    )
    db_session.add(gen)
    db_session.add(
        Score(id="sc1", generation_id="gen1", scorer="dynamics", value={"score": 71.0}),
    )
    db_session.add(
        Score(id="sc2", generation_id="gen1", scorer="silence", value={"other": 0}),
    )
    db_session.commit()

    owner = _owner(db_session, owner_id)
    detail = tools.tool_get_generation(db_session, owner, generation_id="gen1")
    assert detail.id == "gen1"
    assert detail.is_picked is True
    assert detail.scores["dynamics"] == 71.0
    assert detail.scores["silence"] is None


def test_get_generation_blocks_other_user(db_session: Session):
    owner_id, stranger_id, _, song_id, version_id = _seed(db_session)
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
    _, stranger_id, album_id, _, _ = _seed(db_session)
    stranger = _owner(db_session, stranger_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_create_song(
            db_session, stranger, album_id=album_id, title="Sneak",
        )


def test_create_song_rejects_empty_title(db_session: Session):
    owner_id, _, album_id, _, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_create_song(db_session, owner, album_id=album_id, title="  ")


def test_create_song_persists_and_returns_state(db_session: Session):
    owner_id, _, album_id, _, _ = _seed(db_session)
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


def test_update_lyrics_in_place_when_no_generations(db_session: Session):
    owner_id, _, _, song_id, version_id = _seed(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_lyrics(
        db_session, owner, song_id=song_id, lyrics="brand new lyric",
    )
    assert result.song.current_lyrics == "brand new lyric"
    # No new version — updated in place (no generations existed).
    assert len(result.song.versions) == 1
    assert result.song.latest_version_id == version_id


def test_update_lyrics_creates_new_version_when_generated(db_session: Session):
    owner_id, _, _, song_id, version_id = _seed(db_session)
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
    owner_id, _, _, song_id, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_prompt(
        db_session, owner, song_id=song_id, prompt="jazzy bossa",
    )
    assert result.song.current_prompt == "jazzy bossa"
    assert result.song.current_lyrics == "verse one"  # untouched


def test_update_style_requires_at_least_one_param(db_session: Session):
    owner_id, _, _, song_id, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_update_song_style(db_session, owner, song_id=song_id)


def test_update_style_applies_partial(db_session: Session):
    owner_id, _, _, song_id, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_style(
        db_session, owner, song_id=song_id, bpm=88, key_scale="F#m",
    )
    assert result.song.current_bpm == 88
    assert result.song.current_key_scale == "F#m"
    assert result.song.current_audio_duration == 180  # unchanged


def test_update_style_with_duration(db_session: Session):
    owner_id, _, _, song_id, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_update_song_style(
        db_session, owner, song_id=song_id, audio_duration=240,
    )
    assert result.song.current_audio_duration == 240
    assert "duration=240s" in result.message


def test_rename_song(db_session: Session):
    owner_id, _, _, song_id, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    result = tools.tool_rename_song(
        db_session, owner, song_id=song_id, title="Renamed Track",
    )
    assert result.song.title == "Renamed Track"


def test_rename_song_rejects_empty(db_session: Session):
    owner_id, _, _, song_id, _ = _seed(db_session)
    owner = _owner(db_session, owner_id)
    with pytest.raises(tools.MCPToolError):
        tools.tool_rename_song(db_session, owner, song_id=song_id, title="  ")


def test_write_tools_block_other_users(db_session: Session):
    _, stranger_id, _, song_id, _ = _seed(db_session)
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


# ── End-to-end via FastMCP.call_tool ──────────────────────────────────


@pytest.fixture()
def e2e_setup(db_factory, monkeypatch):
    with db_factory() as session:
        owner_id, stranger_id, album_id, song_id, _ = _seed(session)
    monkeypatch.setenv(auth.USER_ID_ENV, owner_id)
    srv = server.build_server(session_factory=db_factory)
    return srv, owner_id, stranger_id, album_id, song_id


def test_e2e_read_and_write(e2e_setup, db_factory):
    srv, _, _, album_id, song_id = e2e_setup
    listed = asyncio.run(srv.call_tool("list_songs", {}))
    payload = _extract_payload(listed)
    assert any(s["id"] == song_id for s in payload)

    updated = asyncio.run(srv.call_tool(
        "update_song_lyrics",
        {"song_id": song_id, "lyrics": "new verse"},
    ))
    payload = _extract_payload(updated)
    assert payload["ok"] is True
    assert payload["song"]["current_lyrics"] == "new verse"


def test_e2e_every_tool_wrapper(e2e_setup, db_factory):
    """Exercise every FastMCP tool wrapper once so server.py is covered."""
    srv, _, _, album_id, song_id = e2e_setup

    # Seed a generation for get_generation
    with db_factory() as session:
        from songmaker_cli.db.models import Generation
        version_id = session.query(Song).filter_by(id=song_id).one().latest_version.id
        session.add(Generation(
            id="gen-e2e", song_id=song_id, version_id=version_id,
            generation_number=1, mp3_path="p/e2e.mp3",
        ))
        session.commit()

    calls: dict[str, dict] = {
        "list_albums": {},
        "list_songs": {"album_id": album_id},
        "search_songs": {"query": "first", "limit": 10},
        "get_song": {"song_id": song_id},
        "get_version": {"song_id": song_id, "version_id": version_id},
        "get_generation": {"generation_id": "gen-e2e"},
        "update_song_prompt": {"song_id": song_id, "prompt": "bossa"},
        "update_song_style": {"song_id": song_id, "bpm": 99},
        "rename_song": {"song_id": song_id, "title": "E2E Renamed"},
        "create_song": {"album_id": album_id, "title": "E2E New"},
    }
    for name, args in calls.items():
        result = asyncio.run(srv.call_tool(name, args))
        payload = _extract_payload(result)
        assert payload is not None, f"{name} returned nothing"


def test_e2e_write_rolled_back_on_access_denied(e2e_setup, db_factory, monkeypatch):
    srv, _, stranger_id, _, song_id = e2e_setup
    monkeypatch.setenv(auth.USER_ID_ENV, stranger_id)
    with pytest.raises(Exception):
        asyncio.run(srv.call_tool(
            "update_song_lyrics",
            {"song_id": song_id, "lyrics": "hijack"},
        ))
    # Ensure no change landed.
    with db_factory() as session:
        song = session.query(Song).filter_by(id=song_id).one()
        assert song.latest_version.lyrics == "verse one"


def test_e2e_missing_env_var_fails(db_factory, monkeypatch):
    monkeypatch.delenv(auth.USER_ID_ENV, raising=False)
    srv = server.build_server(session_factory=db_factory)
    with pytest.raises(Exception):
        asyncio.run(srv.call_tool("list_albums", {}))


def test_e2e_list_albums_returns_structured(e2e_setup):
    srv, _, _, album_id, _ = e2e_setup
    result = asyncio.run(srv.call_tool("list_albums", {}))
    payload = _extract_payload(result)
    assert any(a["id"] == album_id for a in payload)


def test_default_factory_used_when_none_provided(db_factory, monkeypatch):
    """build_server() without explicit factory lazily calls init_db via settings."""
    monkeypatch.setattr(
        "songmaker_cli.mcp_server.server._default_factory",
        lambda: db_factory,
    )
    with db_factory() as session:
        owner_id, _, _, _, _ = _seed(session)
    monkeypatch.setenv(auth.USER_ID_ENV, owner_id)
    srv = server.build_server(session_factory=None)
    result = asyncio.run(srv.call_tool("list_albums", {}))
    payload = _extract_payload(result)
    assert isinstance(payload, list)


def test_default_factory_resolves_via_settings(db_factory, monkeypatch):
    """_default_factory() itself calls init_db(resolve_database_url())."""
    monkeypatch.setattr(
        "songmaker_cli.db.engine.resolve_database_url",
        lambda: "sqlite:///:memory:",
    )
    monkeypatch.setattr(
        "songmaker_cli.db.engine.init_db", lambda _url: db_factory,
    )
    assert server._default_factory() is db_factory


def test_main_runs_server(monkeypatch):
    """main() wires stdio transport — mock FastMCP.run so it doesn't block."""
    called = {}

    def _fake_run(self, transport="stdio", mount_path=None):
        called["transport"] = transport

    monkeypatch.setattr(
        "mcp.server.fastmcp.FastMCP.run", _fake_run,
    )
    monkeypatch.setattr(
        "songmaker_cli.mcp_server.server._default_factory",
        lambda: object(),
    )
    server.main()
    assert called["transport"] == "stdio"


def _extract_payload(call_result):
    # FastMCP.call_tool returns a dict with "result" containing the
    # tool's structured output, or a (content, structured) tuple
    # depending on SDK version. Normalize both.
    if isinstance(call_result, tuple):
        content_blocks, structured = call_result
        if structured is not None:
            return _unwrap_structured(structured)
        return json.loads(content_blocks[0].text)
    if isinstance(call_result, dict):
        return _unwrap_structured(call_result)
    # Fallback — a list/sequence of ContentBlock
    return json.loads(call_result[0].text)


def _unwrap_structured(payload):
    # FastMCP wraps list outputs in {"result": [...]} for JSON-RPC; peel it off.
    if isinstance(payload, dict) and set(payload.keys()) == {"result"}:
        return payload["result"]
    return payload
