"""Tests for ACE-Step worker identity queries."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.db.engine import init_test_db as init_db
from songmaker_cli.db.queries import (
    get_worker_identity,
    list_worker_identities,
    register_worker,
)


@pytest.fixture
def db_session(tmp_path: Path) -> Session:
    factory = init_db(tmp_path / "workers.db")
    session = factory()
    yield session
    session.close()


def test_register_worker_creates_row(db_session: Session) -> None:
    worker = register_worker(
        db_session,
        worker_id="acestep-worker-0",
        host="acestep-worker-0",
        port=8001,
        gpu_id=0,
        vram_total_gb=24.0,
    )
    db_session.commit()

    assert worker.id == "acestep-worker-0"
    assert worker.host == "acestep-worker-0"
    assert worker.port == 8001
    assert worker.gpu_id == 0
    assert worker.vram_total_gb == 24.0
    assert worker.registered_at is not None
    assert worker.last_register_at is not None


def test_register_worker_is_idempotent_upsert(db_session: Session) -> None:
    first = register_worker(
        db_session,
        worker_id="acestep-worker-0",
        host="old-host",
        port=8001,
        gpu_id=0,
        vram_total_gb=24.0,
    )
    db_session.commit()
    original_registered_at = first.registered_at

    second = register_worker(
        db_session,
        worker_id="acestep-worker-0",
        host="new-host",
        port=8002,
        gpu_id=1,
        vram_total_gb=48.0,
    )
    db_session.commit()

    assert second.id == "acestep-worker-0"
    assert second.host == "new-host"
    assert second.port == 8002
    assert second.gpu_id == 1
    assert second.vram_total_gb == 48.0
    assert second.registered_at == original_registered_at
    assert second.last_register_at >= original_registered_at

    rows = list_worker_identities(db_session)
    assert len(rows) == 1


def test_register_worker_allows_null_gpu_and_vram(db_session: Session) -> None:
    worker = register_worker(
        db_session,
        worker_id="cpu-only",
        host="localhost",
        port=8001,
        gpu_id=None,
        vram_total_gb=None,
    )
    db_session.commit()
    assert worker.gpu_id is None
    assert worker.vram_total_gb is None


def test_get_worker_identity_returns_none_for_unknown(db_session: Session) -> None:
    assert get_worker_identity(db_session, "missing") is None


def test_get_worker_identity_returns_existing(db_session: Session) -> None:
    register_worker(
        db_session, worker_id="w1", host="h", port=1, gpu_id=None, vram_total_gb=None,
    )
    db_session.commit()
    found = get_worker_identity(db_session, "w1")
    assert found is not None
    assert found.id == "w1"


def test_list_worker_identities_orders_by_id(db_session: Session) -> None:
    register_worker(
        db_session, worker_id="w-b", host="h", port=1, gpu_id=None, vram_total_gb=None,
    )
    register_worker(
        db_session, worker_id="w-a", host="h", port=2, gpu_id=None, vram_total_gb=None,
    )
    db_session.commit()
    ids = [w.id for w in list_worker_identities(db_session)]
    assert ids == ["w-a", "w-b"]
