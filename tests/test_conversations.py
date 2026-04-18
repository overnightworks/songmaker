"""Tests for the conversation data model + query layer."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import (
    Album,
    ChatMessage,
    Conversation,
    ConversationSummary,
    Song,
    User,
    Version,
)
from songmaker_cli.db.queries import conversations as q


@pytest.fixture()
def db_session(tmp_path: Path) -> Session:
    factory = init_test_db(tmp_path / "conv.db")
    session = factory()
    yield session
    session.close()


def _seed_user(session: Session, user_id: str = "u1") -> User:
    user = User(id=user_id, username=f"user-{user_id}", password_hash="x")
    session.add(user)
    session.flush()
    return user


def _seed_album_song(
    session: Session, user_id: str, album_id: str = "a1", song_id: str = "s1",
) -> tuple[Album, Song]:
    album = Album(id=album_id, title=f"Album {album_id}", artist="x", created_by=user_id)
    song = Song(id=song_id, title=f"Song {song_id}", album_id=album_id, track_number=1)
    version = Version(song_id=song_id, version_number=1, lyrics="", prompt="")
    session.add_all([album, song, version])
    session.flush()
    return album, song


# ── basic CRUD ────────────────────────────────────────────────────────


def test_create_conversation_defaults_to_active(db_session: Session):
    _seed_user(db_session)
    conv = q.create_conversation(db_session, "u1", title="Test")
    db_session.commit()
    assert conv.archived_at is None
    assert conv.title == "Test"
    assert conv.user_id == "u1"


def test_get_active_returns_only_non_archived(db_session: Session):
    _seed_user(db_session)
    archived = q.create_conversation(db_session, "u1")
    archived.archived_at = archived.created_at + timedelta(minutes=1)
    active = q.create_conversation(db_session, "u1")
    db_session.commit()

    fetched = q.get_active_conversation(db_session, "u1")
    assert fetched is not None
    assert fetched.id == active.id


def test_get_active_returns_none_when_all_archived(db_session: Session):
    _seed_user(db_session)
    conv = q.create_conversation(db_session, "u1")
    q.archive_conversation(db_session, conv.id)
    db_session.commit()
    assert q.get_active_conversation(db_session, "u1") is None


def test_get_or_create_active_reuses_existing(db_session: Session):
    _seed_user(db_session)
    first = q.get_or_create_active_conversation(db_session, "u1")
    db_session.commit()
    second = q.get_or_create_active_conversation(db_session, "u1")
    db_session.commit()
    assert first.id == second.id


def test_get_or_create_active_creates_new_after_archive(db_session: Session):
    _seed_user(db_session)
    first = q.get_or_create_active_conversation(db_session, "u1")
    q.archive_conversation(db_session, first.id)
    db_session.commit()
    second = q.get_or_create_active_conversation(db_session, "u1")
    db_session.commit()
    assert first.id != second.id
    assert second.archived_at is None


def test_archive_idempotent(db_session: Session):
    _seed_user(db_session)
    conv = q.create_conversation(db_session, "u1")
    db_session.commit()
    q.archive_conversation(db_session, conv.id)
    first_at = conv.archived_at
    q.archive_conversation(db_session, conv.id)
    assert conv.archived_at == first_at


def test_archive_unknown_id_raises(db_session: Session):
    with pytest.raises(ValueError):
        q.archive_conversation(db_session, "bogus")


def test_list_conversations_filters_archived(db_session: Session):
    _seed_user(db_session)
    active = q.create_conversation(db_session, "u1", title="active")
    archived = q.create_conversation(db_session, "u1", title="archived")
    q.archive_conversation(db_session, archived.id)
    db_session.commit()

    all_ids = {c.id for c in q.list_conversations(db_session, "u1")}
    assert all_ids == {active.id, archived.id}

    active_ids = {
        c.id for c in q.list_conversations(db_session, "u1", include_archived=False)
    }
    assert active_ids == {active.id}


def test_delete_conversation_removes_messages(db_session: Session):
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    q.append_message(db_session, conv.id, "user", "hello", song_id="s1")
    q.append_message(db_session, conv.id, "assistant", "hi", song_id="s1")
    db_session.commit()
    q.delete_conversation(db_session, conv.id)
    db_session.commit()
    assert q.get_conversation(db_session, conv.id) is None
    remaining = db_session.query(ChatMessage).filter_by(conversation_id=conv.id).count()
    assert remaining == 0


def test_delete_unknown_conversation_raises(db_session: Session):
    with pytest.raises(ValueError):
        q.delete_conversation(db_session, "bogus")


# ── messages ──────────────────────────────────────────────────────────


def test_append_message_updates_conversation_timestamp(db_session: Session):
    from datetime import datetime, timezone

    from sqlalchemy import update

    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    db_session.commit()

    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.execute(
        update(Conversation).where(Conversation.id == conv.id)
        .values(updated_at=past),
    )
    db_session.commit()

    q.append_message(db_session, conv.id, "user", "hi", song_id="s1")
    db_session.commit()

    new_updated = db_session.query(Conversation.updated_at).filter_by(id=conv.id).scalar()
    assert _as_naive(new_updated) > _as_naive(past)


def _as_naive(dt):
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def test_list_and_count_messages(db_session: Session):
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    q.append_message(db_session, conv.id, "user", "a", song_id="s1")
    q.append_message(db_session, conv.id, "assistant", "b", song_id="s1")
    db_session.commit()

    assert q.count_messages(db_session, conv.id) == 2
    assert [m.content for m in q.list_messages(db_session, conv.id)] == ["a", "b"]


def test_append_message_without_song(db_session: Session):
    _seed_user(db_session)
    conv = q.create_conversation(db_session, "u1")
    msg = q.append_message(db_session, conv.id, "user", "no-song")
    db_session.commit()
    assert msg.song_id is None


# ── summary ───────────────────────────────────────────────────────────


def test_upsert_summary_inserts_then_updates(db_session: Session):
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    msg = q.append_message(db_session, conv.id, "user", "first", song_id="s1")
    db_session.commit()

    created = q.upsert_summary(
        db_session, conv.id,
        summary_text="S1", last_summarized_message_id=msg.id,
        message_count=1, token_count=5,
    )
    db_session.commit()
    assert created.summary_text == "S1"

    updated = q.upsert_summary(
        db_session, conv.id,
        summary_text="S2", last_summarized_message_id=msg.id,
        message_count=2, token_count=9,
    )
    db_session.commit()
    assert updated.id == created.id
    assert updated.summary_text == "S2"
    assert updated.token_count == 9
    assert db_session.query(ConversationSummary).count() == 1


# ── messages_since ────────────────────────────────────────────────────


def test_messages_since_returns_all_when_boundary_none(db_session: Session):
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    q.append_message(db_session, conv.id, "user", "one", song_id="s1")
    q.append_message(db_session, conv.id, "assistant", "two", song_id="s1")
    db_session.commit()

    got = q.messages_since(db_session, conv.id, since_message_id=None)
    assert [m.content for m in got] == ["one", "two"]


def test_messages_since_exclusive_boundary(db_session: Session):
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    m1 = q.append_message(db_session, conv.id, "user", "one", song_id="s1")
    q.append_message(db_session, conv.id, "assistant", "two", song_id="s1")
    q.append_message(db_session, conv.id, "user", "three", song_id="s1")
    db_session.commit()

    got = q.messages_since(db_session, conv.id, since_message_id=m1.id)
    assert [m.content for m in got] == ["two", "three"]


def test_messages_since_unknown_boundary_returns_all(db_session: Session):
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    q.append_message(db_session, conv.id, "user", "one", song_id="s1")
    db_session.commit()

    got = q.messages_since(db_session, conv.id, since_message_id="nope")
    assert len(got) == 1


# ── recent_conversations ──────────────────────────────────────────────


def test_recent_conversations_counts_messages(db_session: Session):
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1", title="Talking")
    q.append_message(db_session, conv.id, "user", "a", song_id="s1")
    q.append_message(db_session, conv.id, "assistant", "b", song_id="s1")
    empty_conv = q.create_conversation(db_session, "u1", title="Empty")
    db_session.commit()

    rows = q.recent_conversations(db_session, "u1")
    by_id = {r["id"]: r for r in rows}
    assert by_id[conv.id]["message_count"] == 2
    assert by_id[conv.id]["title"] == "Talking"
    assert by_id[empty_conv.id]["message_count"] == 0
    assert by_id[empty_conv.id]["last_message_at"] is None


def test_recent_conversations_scopes_per_user(db_session: Session):
    _seed_user(db_session, "u1")
    _seed_user(db_session, "u2")
    q.create_conversation(db_session, "u1", title="mine")
    q.create_conversation(db_session, "u2", title="yours")
    db_session.commit()

    mine = q.recent_conversations(db_session, "u1")
    assert [r["title"] for r in mine] == ["mine"]


# ── relationship: message in archived conversation survives ───────────


def test_archived_conversation_keeps_messages(db_session: Session):
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    q.append_message(db_session, conv.id, "user", "hi", song_id="s1")
    q.archive_conversation(db_session, conv.id)
    db_session.commit()

    assert q.count_messages(db_session, conv.id) == 1
    refetched = q.get_conversation(db_session, conv.id)
    assert refetched is not None
    assert refetched.archived_at is not None


# ── model: song cascade leaves conversation alone ─────────────────────


def test_song_delete_cascades_chat_messages_but_keeps_conversation(
    db_session: Session,
):
    """Hard-deleting a song still cascades to chat_messages (existing
    behavior preserved after making song_id nullable). The owning
    conversation survives because it is not scoped to the song.
    """
    _seed_user(db_session)
    _seed_album_song(db_session, "u1")
    conv = q.create_conversation(db_session, "u1")
    q.append_message(db_session, conv.id, "user", "hi", song_id="s1")
    db_session.commit()

    song = db_session.query(Song).filter_by(id="s1").one()
    db_session.delete(song)
    db_session.commit()
    assert q.count_messages(db_session, conv.id) == 0
    assert q.get_conversation(db_session, conv.id) is not None


# ── user delete cascades conversations ────────────────────────────────


# ── migration backfill ────────────────────────────────────────────────


def test_backfill_groups_messages_per_album(db_session: Session):
    """The Alembic migration's backfill helper should create one
    archived conversation per album-with-chat and link all that album's
    chat messages to it.
    """
    import importlib

    mig = importlib.import_module(
        "songmaker_cli.db.migrations.versions.d0e1f2a3b4c5_add_conversations",
    )

    u1 = _seed_user(db_session, "u1")
    u2 = _seed_user(db_session, "u2")
    _seed_album_song(db_session, u1.id, album_id="a1", song_id="s1")
    _seed_album_song(db_session, u1.id, album_id="a2", song_id="s2")
    _seed_album_song(db_session, u2.id, album_id="a3", song_id="s3")

    # Legacy rows (conversation_id still NULL).
    for (song_id, content) in [
        ("s1", "a1-msg1"), ("s1", "a1-msg2"),
        ("s2", "a2-msg1"),
        ("s3", "a3-msg1"),
    ]:
        db_session.add(
            ChatMessage(song_id=song_id, role="user", content=content),
        )
    db_session.commit()

    mig.backfill_conversations(db_session.connection())
    db_session.commit()

    convs = db_session.query(Conversation).all()
    assert len(convs) == 3
    assert all(c.archived_at is not None for c in convs)

    # Each album got one conversation with the right user/title.
    by_title = {c.title: c for c in convs}
    assert by_title["Legacy: Album a1"].user_id == "u1"
    assert by_title["Legacy: Album a2"].user_id == "u1"
    assert by_title["Legacy: Album a3"].user_id == "u2"

    # Messages are linked to the matching album's conversation.
    a1_msgs = (
        db_session.query(ChatMessage)
        .filter(ChatMessage.song_id == "s1").all()
    )
    assert all(m.conversation_id == by_title["Legacy: Album a1"].id for m in a1_msgs)


def test_backfill_skips_albums_without_owner(db_session: Session):
    """Orphan albums (created_by is NULL after user deletion) leave
    their chat messages unconverted rather than creating dangling
    conversations.
    """
    import importlib

    mig = importlib.import_module(
        "songmaker_cli.db.migrations.versions.d0e1f2a3b4c5_add_conversations",
    )

    album = Album(id="a1", title="Orphan", artist="x", created_by=None)
    song = Song(id="s1", title="s", album_id="a1", track_number=1)
    db_session.add_all([album, song])
    db_session.flush()
    db_session.add(ChatMessage(song_id="s1", role="user", content="stranded"))
    db_session.commit()

    mig.backfill_conversations(db_session.connection())
    db_session.commit()

    assert db_session.query(Conversation).count() == 0
    msg = db_session.query(ChatMessage).filter_by(song_id="s1").one()
    assert msg.conversation_id is None


def test_backfill_is_idempotent_for_new_messages(db_session: Session):
    """Running the backfill against a DB where some messages already
    have conversation_id (new-flow writes) only touches the legacy
    NULL-conversation_id rows.
    """
    import importlib

    mig = importlib.import_module(
        "songmaker_cli.db.migrations.versions.d0e1f2a3b4c5_add_conversations",
    )

    _seed_user(db_session, "u1")
    _seed_album_song(db_session, "u1", album_id="a1", song_id="s1")
    new_conv = q.create_conversation(db_session, "u1", title="keep-me")
    already = ChatMessage(
        song_id="s1", role="user", content="new-flow",
        conversation_id=new_conv.id,
    )
    legacy = ChatMessage(song_id="s1", role="user", content="legacy")
    db_session.add_all([already, legacy])
    db_session.commit()

    mig.backfill_conversations(db_session.connection())
    db_session.commit()

    db_session.refresh(already)
    db_session.refresh(legacy)
    assert already.conversation_id == new_conv.id
    assert legacy.conversation_id is not None
    assert legacy.conversation_id != new_conv.id


def test_user_delete_cascades_conversations(db_session: Session):
    _seed_user(db_session)
    q.create_conversation(db_session, "u1")
    db_session.commit()

    db_session.query(User).filter_by(id="u1").delete()
    db_session.commit()

    assert db_session.query(Conversation).filter_by(user_id="u1").count() == 0
