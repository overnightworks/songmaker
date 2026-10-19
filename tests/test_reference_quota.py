"""1301-F3-Q: owner inventory, admission, failure and PostgreSQL serialization."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from conftest import make_authenticated_user, make_router_app, make_router_ctx
from fastapi import UploadFile
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from songmaker_cli.db.models import Album, Song, User, Version
from songmaker_cli.generation_api import api_upload_reference_audio
from songmaker_cli.reference_audio import (
    ReferenceAudioQuotaExceeded,
    owner_reference_audio_root,
    store_reference_audio,
)
from songmaker_cli.settings import Settings


@pytest.fixture
def quota_context(tmp_path, request):
    factory = request.getfixturevalue("pg_factory") if "postgresql" in request.node.name else None
    ctx = make_router_ctx(tmp_path, db=factory)
    with ctx.db() as session:
        session.add_all(
            [
                User(id="owner", username="owner", password_hash="unused"),
                User(id="other", username="other", password_hash="unused"),
            ]
        )
        session.commit()
    return ctx


@pytest.mark.acceptance("1301-F3-Q-BOUNDARY")
@pytest.mark.parametrize("field", ["reference_audio_quota_bytes", "reference_audio_quota_files"])
@pytest.mark.parametrize("value", [0, -1])
def test_reference_quotas_must_be_positive(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


def test_reference_quota_defaults_are_decimal_bytes_and_fifty_files():
    settings = Settings()
    assert settings.reference_audio_quota_bytes == 500_000_000
    assert settings.reference_audio_quota_files == 50


@pytest.mark.acceptance("1301-F3-Q-BOUNDARY")
@pytest.mark.parametrize(
    "files,size,byte_limit,file_limit,accepted",
    [
        pytest.param(1, 10, 21, 50, True, id="bytes-below"),
        pytest.param(1, 10, 20, 50, True, id="bytes-exact"),
        pytest.param(1, 10, 19, 50, False, id="bytes-above"),
        pytest.param(1, 10, 1000, 3, True, id="count-below"),
        pytest.param(1, 10, 1000, 2, True, id="count-exact"),
        pytest.param(1, 10, 1000, 1, False, id="count-above"),
        pytest.param(2, 10, 1000, 1, False, id="existing-count-overage"),
        pytest.param(1, 30, 20, 50, False, id="existing-byte-overage"),
    ],
)
def test_reference_admission_boundaries(
    quota_context, files, size, byte_limit, file_limit, accepted
):
    ctx = quota_context
    root = owner_reference_audio_root(ctx.audio_dir, "owner")
    root.mkdir(parents=True)
    for index in range(files):
        (root / f"retained-{index}.wav").write_bytes(b"r" * size)
    with ctx.db() as session:
        session.add(Album(id="album", title="Album", artist="Artist", created_by="owner"))
        session.flush()
        session.add(Song(id="song", title="Song", album_id="album"))
        session.flush()
        session.add(
            Version(
                id="version",
                song_id="song",
                version_number=1,
                generation_params={"reference_audio_path": "owner/refs/retained-0.wav"},
            )
        )
        session.commit()
    settings = Settings(
        reference_audio_quota_bytes=byte_limit, reference_audio_quota_files=file_limit
    )
    before = {entry.name: entry.read_bytes() for entry in root.iterdir()}
    if accepted:
        stored = store_reference_audio(ctx.db, ctx.audio_dir, "owner", ".wav", b"a" * 10, settings)
        assert (ctx.audio_dir / stored).read_bytes() == b"a" * 10
    else:
        with pytest.raises(
            ReferenceAudioQuotaExceeded, match="^Reference audio storage limit reached\\.$"
        ):
            store_reference_audio(ctx.db, ctx.audio_dir, "owner", ".wav", b"a" * 10, settings)
    assert len(list(root.iterdir())) == files + int(accepted)
    assert all((root / name).read_bytes() == content for name, content in before.items())


@pytest.mark.acceptance("1301-F3-Q-FAILURE")
@pytest.mark.parametrize("state", ["unused-upload", "crash-remnant"])
def test_fresh_session_inventory_preserves_all_regular_usage(quota_context, state):
    ctx = quota_context
    settings = Settings(reference_audio_quota_bytes=100, reference_audio_quota_files=2)
    root = owner_reference_audio_root(ctx.audio_dir, "owner")
    if state == "unused-upload":
        store_reference_audio(ctx.db, ctx.audio_dir, "owner", ".wav", b"r" * 100, settings)
    else:
        root.mkdir(parents=True)
        (root / "partial").write_bytes(b"r" * 100)
    fresh_factory = sessionmaker(bind=ctx.db.kw["bind"])
    with pytest.raises(ReferenceAudioQuotaExceeded):
        store_reference_audio(fresh_factory, ctx.audio_dir, "owner", ".wav", b"a", settings)
    assert [entry.read_bytes() for entry in root.iterdir()] == [b"r" * 100]


@pytest.mark.acceptance("1301-F3-Q-FAILURE")
@pytest.mark.parametrize(
    "state,status,detail",
    [
        ("full", 409, "Reference audio storage limit reached."),
        ("unreadable", 500, "Reference audio storage could not be checked."),
        ("nested", 500, "Reference audio storage could not be checked."),
        ("invalid", 400, "Unsupported format '.txt'. Accepted: .flac, .mp3, .ogg, .wav"),
    ],
)
def test_upload_refusals_are_exact_and_preserve_inventory(quota_context, state, status, detail):
    ctx = quota_context
    root = owner_reference_audio_root(ctx.audio_dir, "owner")
    root.mkdir(parents=True)
    retained = root / "retained.wav"
    retained.write_bytes(b"retained")
    if state == "unreadable":
        retained.chmod(0)
    if state == "nested":
        (root / "nested").mkdir()
    app = make_router_app(ctx, user=make_authenticated_user("owner"))
    if state in {"full", "invalid"}:
        for index in range(49):
            (root / f"{index}.wav").write_bytes(b"r")
    try:
        with TestClient(app) as client:
            result = client.post(
                "/api/audio/upload",
                files={
                    "file": ("ref.txt" if state == "invalid" else "ref.wav", b"a" * 100),
                },
            )
        assert result.status_code == status
        assert result.json() == {"detail": detail}
    finally:
        retained.chmod(0o600)
    assert retained.read_bytes() == b"retained"
    assert len(list(root.iterdir())) == (
        50 if state in {"full", "invalid"} else 2 if state == "nested" else 1
    )


@pytest.mark.acceptance("1301-F3-Q-CONCURRENT")
@pytest.mark.parametrize("capacity", ["bytes", "files"])
def test_postgresql_reference_admission_is_atomic(quota_context, capacity):
    ctx = quota_context
    settings = Settings(
        reference_audio_quota_bytes=100 if capacity == "bytes" else 1000,
        reference_audio_quota_files=1 if capacity == "files" else 50,
    )
    start = threading.Barrier(2)

    def upload():
        start.wait(timeout=10)
        try:
            return store_reference_audio(
                ctx.db, ctx.audio_dir, "owner", ".wav", b"a" * 100, settings
            )
        except ReferenceAudioQuotaExceeded:
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: upload(), range(2)))
    assert sum(result is not None for result in results) == 1
    root = owner_reference_audio_root(ctx.audio_dir, "owner")
    assert [entry.read_bytes() for entry in root.iterdir()] == [b"a" * 100]


@pytest.fixture
def held_reference_owner(quota_context):
    entered, release = threading.Event(), threading.Event()

    def hold(session, instance):
        if isinstance(instance, User) and instance.id == "owner":
            entered.set()
            assert release.wait(timeout=15), "Upload was never released"

    event.listen(quota_context.db, "loaded_as_persistent", hold)
    try:
        yield entered, release
    finally:
        release.set()
        event.remove(quota_context.db, "loaded_as_persistent", hold)


@pytest.mark.acceptance("1301-F3-Q-CONCURRENT")
def test_postgresql_reference_owners_do_not_block_each_other(quota_context, held_reference_owner):
    ctx = quota_context
    entered, release = held_reference_owner
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(
            store_reference_audio, ctx.db, ctx.audio_dir, "owner", ".wav", b"a", Settings()
        )
        try:
            assert entered.wait(timeout=10)
            second = workers.submit(
                store_reference_audio, ctx.db, ctx.audio_dir, "other", ".wav", b"b", Settings()
            )
            assert (ctx.audio_dir / second.result(timeout=5)).read_bytes() == b"b"
        finally:
            release.set()
        assert (ctx.audio_dir / first.result(timeout=5)).read_bytes() == b"a"


@pytest.mark.acceptance("1301-F3-Q-CONCURRENT")
def test_postgresql_unrelated_user_write_completes_during_upload(
    quota_context, held_reference_owner
):
    ctx = quota_context
    entered, release = held_reference_owner

    def write_song():
        with ctx.db() as session:
            session.add(Album(id="album", title="Album", artist="Artist", created_by="owner"))
            session.flush()
            session.add(Song(id="song", title="Song", album_id="album"))
            session.commit()
        return "song"

    with ThreadPoolExecutor(max_workers=2) as workers:
        upload = workers.submit(
            store_reference_audio, ctx.db, ctx.audio_dir, "owner", ".wav", b"a", Settings()
        )
        try:
            assert entered.wait(timeout=10)
            assert workers.submit(write_song).result(timeout=5) == "song"
        finally:
            release.set()
        assert (ctx.audio_dir / upload.result(timeout=5)).read_bytes() == b"a"
    with ctx.db() as session:
        assert session.get(Song, "song").album.created_by == "owner"


@pytest.mark.acceptance("1301-F3-Q-FAILURE")
def test_postgresql_cancelled_request_finishes_storage_under_its_lock(
    quota_context, held_reference_owner
):
    ctx = quota_context
    entered, release = held_reference_owner

    async def cancel_upload():
        task = asyncio.create_task(
            api_upload_reference_audio(
                UploadFile(filename="ref.wav", file=BytesIO(b"a" * 100)),
                make_authenticated_user("owner"),
                ctx,
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        return await asyncio.to_thread(
            store_reference_audio,
            ctx.db,
            ctx.audio_dir,
            "owner",
            ".wav",
            b"b" * 100,
            Settings(reference_audio_quota_files=1),
        )

    with pytest.raises(ReferenceAudioQuotaExceeded):
        asyncio.run(cancel_upload())
    root = owner_reference_audio_root(ctx.audio_dir, "owner")
    assert [entry.read_bytes() for entry in root.iterdir()] == [b"a" * 100]


@pytest.mark.acceptance("1301-F3-Q-FAILURE")
@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_postgresql_failed_reference_write_releases_admission(tmp_path, request, backend):
    if backend == "postgresql":
        factory = request.getfixturevalue("pg_factory")
    else:
        factory = make_router_ctx(tmp_path).db
    with factory() as session:
        session.add(User(id="owner", username="owner", password_hash="unused"))
        session.commit()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os, resource, signal, sys
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from songmaker_cli.reference_audio import (
    store_reference_audio, ReferenceAudioStorageError, ReferenceAudioQuotaExceeded,
)
from songmaker_cli.settings import Settings
factory = sessionmaker(bind=create_engine(os.environ["REFERENCE_TEST_DB"]))
root = Path(sys.argv[1])
settings = Settings(reference_audio_quota_bytes=10000)
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
original = resource.getrlimit(resource.RLIMIT_FSIZE)
resource.setrlimit(resource.RLIMIT_FSIZE, (1024, original[1]))
try:
    try:
        store_reference_audio(factory, root, "owner", ".wav", b"x" * 8192, settings)
    except ReferenceAudioStorageError:
        pass
    else:
        raise AssertionError("write should exceed filesystem limit")
finally:
    resource.setrlimit(resource.RLIMIT_FSIZE, original)
assert list((root / "owner" / "refs").iterdir()) == []
(root / "owner" / "refs" / "crash-remnant").write_bytes(b"r" * 9900)
stored = store_reference_audio(factory, root, "owner", ".wav", b"a" * 100, settings)
assert (root / stored).read_bytes() == b"a" * 100
try:
    store_reference_audio(factory, root, "owner", ".wav", b"b", settings)
except ReferenceAudioQuotaExceeded:
    pass
else:
    raise AssertionError("surviving bytes were not counted")
""",
            str(tmp_path / "audio"),
        ],
        env={
            **os.environ,
            "REFERENCE_TEST_DB": factory.kw["bind"].url.render_as_string(hide_password=False),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
