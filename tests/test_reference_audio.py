"""Owner-root resolution for reference audio."""

from __future__ import annotations

from pathlib import Path

import pytest
from support.web_app import make_test_app, seed_session

from songmaker_cli.constants import REFERENCE_AUDIO_DIR
from songmaker_cli.db.models import Album, Song, User
from songmaker_cli.reference_audio import (
    ReferenceAudioRejected,
    resolve_owned_reference_audio,
)


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


def test_a_symlink_entry_without_a_row_is_left_alone_by_an_upload(tmp_path: Path) -> None:
    """Q6: an unrecorded entry neither blocks the upload nor is followed."""
    from support.web_app import make_router_ctx

    from songmaker_cli.reference_audio import store_reference_audio
    from songmaker_cli.settings import Settings

    audio_dir = tmp_path / "audio"
    foreign, link = _symlink_to_foreign_secret(audio_dir)
    ctx = make_router_ctx(tmp_path, seed_db=_seed_users)
    stored = store_reference_audio(
        ctx.db, audio_dir, "user-a", ".wav", b"audio", Settings(), "ref.wav",
    )
    assert foreign.read_bytes() == b"SECRET"
    assert link.is_symlink()
    assert (audio_dir / stored).read_bytes() == b"audio"


@pytest.mark.parametrize("name", ["missing.wav", "unsupported.txt"])
def test_rejects_missing_or_unsupported_owned_reference_audio(tmp_path: Path, name: str) -> None:
    audio_dir = tmp_path / "audio"
    if name == "unsupported.txt":
        _write_ref(audio_dir, "user-a", name)

    with pytest.raises(ReferenceAudioRejected, match="reference audio path is not owned"):
        resolve_owned_reference_audio(audio_dir, "user-a", f"user-a/{REFERENCE_AUDIO_DIR}/{name}")


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


def test_song_write_accepts_owned_reference_and_rejects_foreign(
    tmp_path: Path,
) -> None:
    client, factory = make_test_app(tmp_path, seed_db=_seed_users)
    seed_session(client, "owner")
    audio_dir = tmp_path / "audio"
    _write_ref(audio_dir, "user-a", "mine.wav")
    _write_ref(audio_dir, "user-b", "secret.wav", b"SECRET")

    own_resp = client.post("/api/songs", json={
        "title": "Own ref",
        "album_id": "album-a",
        "generation_params": {
            "reference_audio_path": f"user-a/{REFERENCE_AUDIO_DIR}/mine.wav",
        },
    })
    assert own_resp.status_code == 200, own_resp.text

    foreign_resp = client.post("/api/songs", json={
        "title": "Foreign ref",
        "album_id": "album-a",
        "generation_params": {
            "reference_audio_path": f"user-b/{REFERENCE_AUDIO_DIR}/secret.wav",
        },
    })
    assert foreign_resp.status_code == 404
    assert foreign_resp.json()["detail"] == "Not Found"
    with factory() as session:
        assert session.query(Song).filter_by(title="Foreign ref").first() is None


@pytest.mark.parametrize("entry_kind", ["foreign-root", "ancestor-symlink"])
def test_admission_rejects_a_symlinked_owner_root_or_ancestor(tmp_path, entry_kind):
    """Q7: nothing is written through a symlink."""
    from support.web_app import make_router_ctx

    from songmaker_cli.db.models import ReferenceRecording
    from songmaker_cli.reference_audio import (
        ReferenceAudioStorageError,
        owner_reference_audio_root,
        store_reference_audio,
    )
    from songmaker_cli.settings import Settings

    ctx = make_router_ctx(tmp_path, seed_db=_seed_users)
    foreign = _write_ref(ctx.audio_dir, "user-b", "secret.wav", b"SECRET")
    root = owner_reference_audio_root(ctx.audio_dir, "user-a")
    if entry_kind == "foreign-root":
        root.parent.mkdir()
        root.symlink_to(foreign.parent, target_is_directory=True)
    else:
        root.parent.symlink_to(foreign.parent.parent, target_is_directory=True)
    before = set(ctx.audio_dir.rglob("*"))
    with pytest.raises(
        ReferenceAudioStorageError, match="Reference audio storage could not be checked"
    ):
        store_reference_audio(
            ctx.db, ctx.audio_dir, "user-a", ".wav", b"a" * 100, Settings(), "ref.wav",
        )
    assert foreign.read_bytes() == b"SECRET"
    assert set(ctx.audio_dir.rglob("*")) == before
    with ctx.db() as session:
        assert session.query(ReferenceRecording).count() == 0


@pytest.mark.parametrize("entry_kind", ["nested-directory", "fifo", "unreadable-file"])
def test_unrecorded_entries_under_the_owner_root_do_not_block_an_upload(tmp_path, entry_kind):
    """Q6: only rows count, so entries nobody recorded cannot refuse an upload."""
    import os

    from support.web_app import make_router_ctx

    from songmaker_cli.reference_audio import owner_reference_audio_root, store_reference_audio
    from songmaker_cli.settings import Settings

    ctx = make_router_ctx(tmp_path, seed_db=_seed_users)
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
    assert (ctx.audio_dir / stored).read_bytes() == b"a" * 100


def test_missing_reference_owner_is_refused_before_directory_creation(tmp_path):
    """Q8: no directory and no row for an owner without a user row."""
    from support.web_app import make_router_ctx

    from songmaker_cli.db.models import ReferenceRecording
    from songmaker_cli.reference_audio import ReferenceAudioStorageError, store_reference_audio
    from songmaker_cli.settings import Settings

    ctx = make_router_ctx(tmp_path)
    settings = Settings()
    with pytest.raises(ReferenceAudioStorageError):
        store_reference_audio(
            ctx.db, ctx.audio_dir, "missing", ".wav", b"a", settings, "ref.wav",
        )
    assert not ctx.audio_dir.exists()
    with ctx.db() as session:
        assert session.query(ReferenceRecording).count() == 0
