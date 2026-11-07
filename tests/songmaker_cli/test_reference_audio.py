"""Owner-root resolution for reference audio."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.reference_rows import a_reference
from support.web_app import make_test_app, seed_session

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, ReferenceRecording, Song, User, Version
from songmaker_cli.reference_audio import (
    ReferenceAudioRejected,
    RemovalOutcome,
    remove_reference_file,
    resolve_owned_reference_audio,
)
from songmaker_cli.timestamps import utcnow


def _write_ref(root: Path, user_id: str, name: str, data: bytes = b"RIFF") -> Path:
    dest = root / user_id / REFERENCE_AUDIO_DIR / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def test_resolves_owned_regular_file(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a", "clip.wav")
    resolved = resolve_owned_reference_audio(
        audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/clip.wav",
    )
    assert resolved.is_file()
    assert resolved.name == "clip.wav"


def test_rejects_cross_user_path(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-b", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-b/{REFERENCE_AUDIO_DIR}/clip.wav",
        )


def test_rejects_user_id_sibling_prefix(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a-other", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a-other/{REFERENCE_AUDIO_DIR}/clip.wav",
        )


def test_rejects_traversal(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/../clip.wav",
        )


def test_rejects_absolute_path(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    dest = _write_ref(audio_dir, "user-a", "clip.wav")
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(audio_dir, "user-a", str(dest))


def _symlink_to_foreign_secret(audio_dir: Path) -> tuple[Path, Path]:
    foreign = _write_ref(audio_dir, "user-b", "secret.wav", b"SECRET")
    link_dir = audio_dir / "user-a" / REFERENCE_AUDIO_DIR
    link_dir.mkdir(parents=True, exist_ok=True)
    link = link_dir / "alias.wav"
    link.symlink_to(foreign)
    return foreign, link


def test_rejects_symlink_outside_owner_root(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    foreign, link = _symlink_to_foreign_secret(audio_dir)
    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/alias.wav",
        )
    assert foreign.read_bytes() == b"SECRET"
    assert list(link.parent.iterdir()) == [link]


def test_a_symlink_entry_without_a_row_is_left_alone_by_an_upload(
    tmp_path: Path, pg_factory,
) -> None:
    """Q6: an unrecorded entry neither blocks the upload nor is followed."""
    from support.web_app import make_router_ctx

    from songmaker_cli.reference_audio import store_reference_audio
    from songmaker_cli.settings import Settings

    audio_dir = tmp_path / "audio"
    foreign, link = _symlink_to_foreign_secret(audio_dir)
    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=_seed_users)
    stored = store_reference_audio(
        ctx.db, audio_dir, "user-a", ".wav", b"audio", Settings(), "ref.wav",
    )
    assert foreign.read_bytes() == b"SECRET"
    assert link.is_symlink()
    assert (audio_dir / stored.storage_path).read_bytes() == b"audio"


@pytest.mark.parametrize("name", ["missing.wav", "unsupported.txt"])
def test_rejects_missing_or_unsupported_owned_reference_audio(tmp_path: Path, name: str) -> None:
    audio_dir = tmp_path / "audio"
    if name == "unsupported.txt":
        _write_ref(audio_dir, "user-a", name)

    with pytest.raises(ReferenceAudioRejected, match="reference audio path is not owned"):
        resolve_owned_reference_audio(audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/{name}")


def test_a_nested_path_is_refused_although_its_file_exists(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    nested = audio_dir / "user-a" / REFERENCE_AUDIO_DIR / "sub" / "x.wav"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"RIFF")

    with pytest.raises(ReferenceAudioRejected):
        resolve_owned_reference_audio(
            audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/sub/x.wav",
        )


def test_remove_reference_file_removes_the_owners_file(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    kept = _write_ref(audio_dir, "user-a", "other.wav")
    gone = _write_ref(audio_dir, "user-a", "clip.wav")

    outcome = remove_reference_file(audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/clip.wav")

    assert outcome is RemovalOutcome.REMOVED
    assert not gone.exists()
    assert kept.exists()


@pytest.mark.parametrize("directory_exists", [True, False])
def test_remove_reference_file_reports_an_absent_file_as_already_gone(
    tmp_path: Path, directory_exists: bool,
) -> None:
    audio_dir = tmp_path / "audio"
    if directory_exists:
        _write_ref(audio_dir, "user-a", "other.wav")

    outcome = remove_reference_file(audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/clip.wav")

    assert outcome is RemovalOutcome.ALREADY_GONE


@pytest.mark.parametrize("owner_directory", ["user-b", ".."])
def test_remove_reference_file_fails_for_a_path_of_another_owner(
    tmp_path: Path, owner_directory: str,
) -> None:
    audio_dir = tmp_path / "audio"
    own = _write_ref(audio_dir, "user-a", "x.wav")

    outcome = remove_reference_file(
        audio_dir, "user-a", f"{owner_directory}/{REFERENCE_AUDIO_DIR}/x.wav",
    )

    assert outcome is RemovalOutcome.FAILED
    assert own.exists()


def test_remove_reference_file_fails_through_a_symlinked_ancestor(tmp_path: Path) -> None:
    audio_dir = tmp_path / "audio"
    foreign = _write_ref(audio_dir, "user-b", "clip.wav")
    (audio_dir / "user-a").mkdir(parents=True)
    (audio_dir / "user-a" / REFERENCE_AUDIO_DIR).symlink_to(foreign.parent)

    outcome = remove_reference_file(audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/clip.wav")

    assert outcome is RemovalOutcome.FAILED
    assert foreign.exists()


def _seed_users(session) -> None:
    session.add_all([
        User(
            id="user-a", username="owner",
        ),
        User(
            id="user-b", username="other",
        ),
    ])
    session.flush()
    session.add(Album(id="album-a", title="A", artist="A", created_by="user-a"))


def _record_reference(factory, user_id: str, name: str = "mine.wav") -> str:
    with factory() as session:
        recording = a_reference(session, user_id, name=name, unused_since=utcnow())
        session.commit()
        return recording.id


@pytest.fixture
def world(tmp_path: Path, pg_factory):
    client, factory = make_test_app(tmp_path, factory=pg_factory, seed_db=_seed_users)
    seed_session(client, "owner")
    return client, factory


def _linked_ids(factory, song_id: str) -> list[str | None]:
    with factory() as session:
        versions = (
            session.query(Version).filter_by(song_id=song_id).order_by(Version.version_number)
        )
        return [version.reference_recording_id for version in versions]


def test_create_with_an_owned_reference_links_the_row_and_answers_its_filename(world) -> None:
    client, factory = world
    reference_id = _record_reference(factory, "user-a")

    response = client.post("/api/songs", json={
        "title": "Own ref", "album_id": "album-a", "reference_recording_id": reference_id,
    })

    assert response.status_code == 200, response.text
    assert response.json()["reference"] == {
        "id": reference_id, "filename": "mine.wav",
    }
    assert _linked_ids(factory, response.json()["id"]) == [reference_id]


def _unused_since(factory, reference_id: str):
    with factory() as session:
        return session.get(ReferenceRecording, reference_id).unused_since


@pytest.mark.parametrize("route", ["create", "update", "update_as_new_version"])
def test_saving_a_version_with_a_reference_commits_it_unstamped(world, route: str) -> None:
    client, factory = world
    reference_id = _record_reference(factory, "user-a")
    bystander_id = _record_reference(factory, "user-a", "bystander.wav")
    song_id = client.post("/api/songs", json={"title": "S", "album_id": "album-a"}).json()["id"]
    assert _unused_since(factory, reference_id) is not None

    if route == "create":
        response = client.post("/api/songs", json={
            "title": "Own ref", "album_id": "album-a", "reference_recording_id": reference_id,
        })
    else:
        response = client.put(f"/api/songs/{song_id}", json={
            "reference_recording_id": reference_id, "new_version": route == "update_as_new_version",
        })

    assert response.status_code == 200, response.text
    assert _unused_since(factory, reference_id) is None
    assert _unused_since(factory, bystander_id) is not None


def test_create_without_the_field_links_nothing(world) -> None:
    client, factory = world

    response = client.post("/api/songs", json={"title": "Plain", "album_id": "album-a"})

    assert response.json()["reference"] is None
    assert _linked_ids(factory, response.json()["id"]) == [None]


@pytest.mark.parametrize("owner", ["user-b", None])
@pytest.mark.parametrize("route", ["create", "update"])
def test_a_foreign_or_unknown_reference_answers_404_and_writes_nothing(
    world, route: str, owner: str | None,
) -> None:
    client, factory = world
    reference_id = _record_reference(factory, owner, "secret.wav") if owner else "unknown-id"
    song_id = client.post("/api/songs", json={"title": "S", "album_id": "album-a"}).json()["id"]

    if route == "create":
        response = client.post("/api/songs", json={
            "title": "Foreign", "album_id": "album-a", "reference_recording_id": reference_id,
        })
    else:
        response = client.put(
            f"/api/songs/{song_id}", json={"reference_recording_id": reference_id},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    with factory() as session:
        assert session.query(Song).filter_by(title="Foreign").first() is None
        assert all(row.unused_since is not None for row in session.query(ReferenceRecording))
    assert _linked_ids(factory, song_id) == [None]


def test_update_carries_the_link_unless_the_field_is_sent(world) -> None:
    client, factory = world
    reference_id = _record_reference(factory, "user-a")
    song_id = client.post("/api/songs", json={
        "title": "S", "album_id": "album-a", "reference_recording_id": reference_id,
    }).json()["id"]

    client.put(f"/api/songs/{song_id}", json={"prompt": "in place"})
    client.put(f"/api/songs/{song_id}", json={"prompt": "branch", "new_version": True})
    assert _linked_ids(factory, song_id) == [reference_id, reference_id]

    cleared = client.put(f"/api/songs/{song_id}", json={"reference_recording_id": None})
    assert cleared.json()["reference"] is None
    assert _linked_ids(factory, song_id) == [reference_id, None]


def test_a_version_request_still_sending_the_path_is_refused(world) -> None:
    client, factory = world
    song_id = client.post("/api/songs", json={"title": "S", "album_id": "album-a"}).json()["id"]
    path = {"generation_params": {"reference_audio_path": "user-a/refs/mine.wav"}}

    created = client.post("/api/songs", json={"title": "T", "album_id": "album-a", **path})
    assert created.status_code == 422
    assert client.put(f"/api/songs/{song_id}", json=path).status_code == 422


@pytest.mark.parametrize("entry_kind", ["foreign-root", "ancestor-symlink"])
def test_admission_rejects_a_symlinked_owner_root_or_ancestor(tmp_path, entry_kind, pg_factory):
    """Q7: nothing is written through a symlink."""
    from support.web_app import make_router_ctx

    from songmaker_cli.db.models import ReferenceRecording
    from songmaker_cli.reference_audio import (
        ReferenceAudioStorageError,
        owner_reference_audio_root,
        store_reference_audio,
    )
    from songmaker_cli.settings import Settings

    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=_seed_users)
    foreign = _write_ref(ctx.audio_dir, "user-b", "secret.wav", b"SECRET")
    root = owner_reference_audio_root(ctx.audio_dir, "user-a")
    if entry_kind == "foreign-root":
        root.parent.mkdir()
        root.symlink_to(foreign.parent, target_is_directory=True)
    else:
        root.parent.symlink_to(foreign.parent.parent, target_is_directory=True)
    before = set(ctx.audio_dir.rglob("*"))
    settings = Settings()
    with pytest.raises(
        ReferenceAudioStorageError, match="Reference audio storage could not be checked"
    ):
        store_reference_audio(
            ctx.db, ctx.audio_dir, "user-a", ".wav", b"a" * 100, settings, "ref.wav",
        )
    assert foreign.read_bytes() == b"SECRET"
    assert set(ctx.audio_dir.rglob("*")) == before
    with ctx.db() as session:
        assert session.query(ReferenceRecording).count() == 0


@pytest.mark.parametrize("entry_kind", ["nested-directory", "fifo", "unreadable-file"])
def test_unrecorded_entries_under_the_owner_root_do_not_block_an_upload(
    tmp_path, entry_kind, pg_factory,
):
    """Q6: only rows count, so entries nobody recorded cannot refuse an upload."""
    import os

    from support.web_app import make_router_ctx

    from songmaker_cli.reference_audio import owner_reference_audio_root, store_reference_audio
    from songmaker_cli.settings import Settings

    ctx = make_router_ctx(tmp_path, db=pg_factory, seed_db=_seed_users)
    root = owner_reference_audio_root(ctx.audio_dir, "user-a")
    root.mkdir(parents=True)
    if entry_kind == "nested-directory":
        (root / "nested").mkdir()
    elif entry_kind == "fifo":
        os.mkfifo(root / "pipe")
    else:
        unreadable = root / "unreadable.wav"
        unreadable.write_bytes(b"retained")
        unreadable.chmod(0)
    try:
        stored = store_reference_audio(
            ctx.db, ctx.audio_dir, "user-a", ".wav", b"a" * 100, Settings(), "ref.wav",
        )
    finally:
        if entry_kind == "unreadable-file":
            unreadable.chmod(0o600)
    assert (ctx.audio_dir / stored.storage_path).read_bytes() == b"a" * 100


def test_missing_reference_owner_is_refused_before_directory_creation(tmp_path, pg_factory):
    """Q8: no directory and no row for an owner without a user row."""
    from support.web_app import make_router_ctx

    from songmaker_cli.db.models import ReferenceRecording
    from songmaker_cli.reference_audio import ReferenceAudioStorageError, store_reference_audio
    from songmaker_cli.settings import Settings

    ctx = make_router_ctx(tmp_path, db=pg_factory)
    settings = Settings()
    with pytest.raises(ReferenceAudioStorageError):
        store_reference_audio(
            ctx.db, ctx.audio_dir, "missing", ".wav", b"a", settings, "ref.wav",
        )
    assert not ctx.audio_dir.exists()
    with ctx.db() as session:
        assert session.query(ReferenceRecording).count() == 0
