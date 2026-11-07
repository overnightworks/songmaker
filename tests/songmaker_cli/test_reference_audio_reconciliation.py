"""The daily run removes reference files that no row names, and nothing else."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import sessionmaker
from support.reference_rows import a_reference
from support.web_app import make_router_ctx

from songmaker_cli.db.models import ReferenceRecording, User
from songmaker_cli.reference_audio import (
    ReferenceAudioStorageError,
    RemnantReport,
    owner_reference_audio_root,
    reconcile_reference_remnants,
    store_reference_audio,
)
from songmaker_cli.settings import Settings

PRIVATE_NAME = "private-take-name"
READ_ONLY_OWNER = "qzx81"


@pytest.fixture
def ctx(tmp_path, pg_factory):
    def seed(session):
        session.add_all([
            User(id=user_id, username=user_id) for user_id in ("owner", "other", READ_ONLY_OWNER)
        ])

    return make_router_ctx(tmp_path, db=pg_factory, seed_db=seed)


def _refs(ctx, user_id="owner") -> Path:
    return owner_reference_audio_root(ctx.audio_dir, user_id)


def _file(ctx, name, user_id="owner", content=b"audio") -> Path:
    path = _refs(ctx, user_id) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _row(ctx, name, user_id="owner", storage_path=None) -> None:
    with ctx.db() as session:
        a_reference(
            session, user_id, name=name, size_bytes=5, storage_path=storage_path,
            original_filename="x.wav",
        )
        session.commit()


def _reconcile(ctx) -> RemnantReport:
    return reconcile_reference_remnants(ctx.db, ctx.audio_dir)


def test_remnants_go_and_every_file_a_row_names_stays(ctx):
    kept, remnant = _file(ctx, "kept.wav"), _file(ctx, "remnant.wav")
    _row(ctx, "kept.wav")
    other_remnant = _file(ctx, "other.wav", "other")
    outside = ctx.audio_dir / "owner" / "song.mp3"
    outside.write_bytes(b"x")

    report = _reconcile(ctx)

    assert report == RemnantReport(removed=2)
    assert kept.exists()
    assert outside.exists()
    assert not remnant.exists()
    assert not other_remnant.exists()


def test_a_file_named_by_another_owners_row_is_a_remnant(ctx):
    taken = _file(ctx, "shared.wav")
    _row(ctx, "shared.wav", "other")

    assert _reconcile(ctx).removed == 1
    assert not taken.exists()


def test_symlinks_directories_and_fifos_are_neither_followed_nor_removed(ctx):
    outside = ctx.audio_dir / "outside.wav"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_bytes(b"x")
    _file(ctx, "anchor.wav")
    refs = _refs(ctx)
    (refs / "link.wav").symlink_to(outside)
    (refs / "nested").mkdir()
    (refs / "nested" / "inner.wav").write_bytes(b"x")
    os.mkfifo(refs / "pipe.wav")

    report = _reconcile(ctx)

    assert report == RemnantReport(removed=1, refused=3)
    assert outside.exists()
    assert (refs / "nested" / "inner.wav").exists()
    assert (refs / "link.wav").is_symlink()
    assert (refs / "pipe.wav").exists()


@pytest.mark.parametrize("linked", ["refs", "owner"])
def test_a_symlinked_directory_refuses_that_owner_and_the_others_still_run(ctx, linked):
    target = ctx.audio_dir / "elsewhere"
    (target / "refs").mkdir(parents=True)
    victim = target / "refs" / "victim.wav"
    victim.write_bytes(b"x")
    if linked == "owner":
        (ctx.audio_dir / "owner").symlink_to(target)
    else:
        (ctx.audio_dir / "owner").mkdir()
        (ctx.audio_dir / "owner" / "refs").symlink_to(target / "refs")
    other_remnant = _file(ctx, "other.wav", "other")

    report = _reconcile(ctx)

    assert report == RemnantReport(removed=1, failed_owners=1)
    assert victim.exists()
    assert not other_remnant.exists()


def test_a_non_directory_ancestor_refuses_that_owner(ctx):
    (ctx.audio_dir).mkdir(parents=True)
    (ctx.audio_dir / "owner").write_bytes(b"x")

    assert _reconcile(ctx) == RemnantReport(failed_owners=1)


def test_an_unreadable_refs_directory_fails_that_owner_and_the_others_still_run(ctx):
    unreadable = _file(ctx, "kept.wav").parent
    other_remnant = _file(ctx, "other.wav", "other")
    unreadable.chmod(0)
    try:
        report = _reconcile(ctx)
    finally:
        unreadable.chmod(0o700)

    assert report == RemnantReport(removed=1, failed_owners=1)
    assert not other_remnant.exists()


@pytest.mark.parametrize(
    "storage_path",
    [
        "owner/refs/nested/a.wav", "other/refs/a.wav", "owner/a.wav", "owner/refs//a.wav",
        "owner/refs/..", "owner/refs/.",
    ],
)
def test_an_owner_with_a_non_conforming_row_path_keeps_every_file(ctx, storage_path):
    remnant = _file(ctx, "remnant.wav")
    _row(ctx, "a.wav", storage_path=storage_path)

    assert _reconcile(ctx) == RemnantReport(failed_owners=1)
    assert remnant.exists()


def test_a_failure_to_list_the_users_ends_the_run_loudly(tmp_path, empty_postgresql_url):
    engine = create_engine(empty_postgresql_url)
    empty_database = sessionmaker(bind=engine)
    try:
        with pytest.raises(ProgrammingError):
            reconcile_reference_remnants(empty_database, tmp_path)
    finally:
        engine.dispose()


def test_a_missing_refs_directory_is_not_created(ctx):
    assert _reconcile(ctx) == RemnantReport()
    assert not (ctx.audio_dir / "owner").exists()
    assert not (ctx.audio_dir / "other").exists()


def test_a_file_that_vanishes_before_its_unlink_counts_as_done(ctx, monkeypatch):
    vanishing = _file(ctx, "vanishing.wav")
    real_unlink = os.unlink

    def unlink_after_a_concurrent_removal(name, *, dir_fd):
        real_unlink(name, dir_fd=dir_fd)
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", unlink_after_a_concurrent_removal)

    assert _reconcile(ctx).failed_owners == 0
    assert not vanishing.exists()


@pytest.mark.parametrize("listener", ["before_commit", "after_commit"])
def test_an_upload_whose_commit_raised_keeps_its_file_only_while_a_row_exists(ctx, listener):
    def lose_the_confirmation(_session):
        raise OperationalError("COMMIT", {}, ConnectionError("lost"))

    settings = Settings()
    event.listen(ctx.db, listener, lose_the_confirmation)
    try:
        with pytest.raises(ReferenceAudioStorageError):
            store_reference_audio(
                ctx.db, ctx.audio_dir, "owner", ".wav", b"audio", settings, "x.wav",
            )
    finally:
        event.remove(ctx.db, listener, lose_the_confirmation)
    [stored] = list(_refs(ctx).iterdir())
    with ctx.db() as session:
        has_row = session.query(ReferenceRecording).count() == 1

    _reconcile(ctx)

    assert stored.exists() is has_row
    assert has_row is (listener == "after_commit")


@pytest.fixture
def read_only_refs(ctx):
    """An owner whose refs directory refuses unlinks, so the failure names a file."""
    private = _file(ctx, f"{PRIVATE_NAME}-locked.wav", READ_ONLY_OWNER)
    refs = private.parent
    refs.chmod(0o500)
    try:
        yield refs
    finally:
        refs.chmod(0o700)


@pytest.mark.skipif(os.geteuid() == 0, reason="root unlinks from a read-only directory")
def test_the_logs_carry_the_user_and_never_a_name_or_a_path(ctx, caplog, read_only_refs):
    _file(ctx, f"{PRIVATE_NAME}.wav")
    (_refs(ctx) / f"{PRIVATE_NAME}-link.wav").symlink_to(ctx.audio_dir)
    (ctx.audio_dir / "other").write_bytes(b"x")

    with caplog.at_level(logging.DEBUG):
        report = _reconcile(ctx)

    assert report.failed_owners == 2
    assert READ_ONLY_OWNER in caplog.text
    assert "other" in caplog.text
    assert PRIVATE_NAME not in caplog.text
    assert str(ctx.audio_dir) not in caplog.text


def test_an_owner_that_fails_partway_keeps_the_count_of_the_files_it_removed(ctx, monkeypatch):
    _file(ctx, "one.wav")
    _file(ctx, "two.wav")
    real_unlink = os.unlink
    calls = []

    def fail_the_second_unlink(name, *, dir_fd):
        calls.append(name)
        if len(calls) == 2:
            raise PermissionError(name)
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr(os, "unlink", fail_the_second_unlink)

    assert _reconcile(ctx) == RemnantReport(removed=1, failed_owners=1)
