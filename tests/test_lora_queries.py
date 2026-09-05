"""Tests for UserLora + UserLoraSample DB query functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from songmaker_cli.constants import (
    MODEL_DEFAULT_MODE,
    JobStatus,
    JobType,
    LoraStatus,
)
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Job, User
from songmaker_cli.db.queries import (
    add_user_lora_sample,
    count_user_lora_samples,
    create_user_lora,
    delete_user_lora_sample,
    get_user_lora,
    get_user_lora_sample,
    list_active_user_loras,
    list_user_loras_for_user,
    restore_user_lora,
    soft_delete_user_lora,
    update_user_lora,
    update_user_lora_sample,
)

_USER_A = "u-a"
_USER_B = "u-b"


@pytest.fixture
def session(tmp_path: Path) -> Session:
    factory = init_test_db(tmp_path / "loras.db")
    s = factory()
    s.add(User(id=_USER_A, username="alice", password_hash="x", role="user"))
    s.add(User(id=_USER_B, username="bob", password_hash="x", role="user"))
    s.commit()
    yield s
    s.close()


def test_create_lora_defaults_to_draft(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "My Voice", "my-voice")
    session.commit()
    assert lora.id
    assert lora.status == LoraStatus.DRAFT
    assert lora.model_mode == MODEL_DEFAULT_MODE
    assert lora.deleted_at is None
    assert lora.storage_path is None


@pytest.mark.parametrize("model_mode", ["sft", "turbo"])
def test_create_lora_accepts_training_model_modes(session: Session, model_mode: str) -> None:
    lora = create_user_lora(
        session,
        _USER_A,
        "My Voice",
        f"my-voice-{model_mode}",
        model_mode=model_mode,
    )

    assert lora.model_mode == model_mode


@pytest.mark.parametrize("model_mode", ["xl-sft", "xl-turbo", "xl-base"])
def test_create_lora_rejects_non_training_model_modes(
    session: Session, model_mode: str,
) -> None:
    with pytest.raises(ValueError, match="Unsupported LoRA training model mode"):
        create_user_lora(session, _USER_A, "My Voice", "my-voice", model_mode=model_mode)


def test_get_user_lora_hides_soft_deleted_by_default(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "Voice", "voice")
    session.commit()
    soft_delete_user_lora(session, lora.id)
    session.commit()

    assert get_user_lora(session, lora.id) is None
    assert get_user_lora(session, lora.id, include_deleted_rows=True) is not None


def test_list_user_loras_scoped_to_user(session: Session) -> None:
    create_user_lora(session, _USER_A, "A1", "a1")
    create_user_lora(session, _USER_A, "A2", "a2")
    create_user_lora(session, _USER_B, "B1", "b1")
    session.commit()

    a_loras = list_user_loras_for_user(session, _USER_A)
    assert {row.name for row in a_loras} == {"A1", "A2"}
    b_loras = list_user_loras_for_user(session, _USER_B)
    assert {row.name for row in b_loras} == {"B1"}


def test_list_user_loras_excludes_deleted_by_default(session: Session) -> None:
    keep = create_user_lora(session, _USER_A, "Keep", "keep")
    gone = create_user_lora(session, _USER_A, "Gone", "gone")
    session.commit()
    soft_delete_user_lora(session, gone.id)
    session.commit()

    default = list_user_loras_for_user(session, _USER_A)
    assert {row.id for row in default} == {keep.id}

    with_deleted = list_user_loras_for_user(session, _USER_A, include_deleted=True)
    assert {row.id for row in with_deleted} == {keep.id, gone.id}


def test_update_user_lora_sets_fields(session: Session) -> None:
    from datetime import datetime, timezone

    lora = create_user_lora(session, _USER_A, "L", "l")
    session.add(Job(id="job-xyz", type="lora_training", user_id=_USER_A))
    session.commit()
    completed = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)
    update_user_lora(
        session, lora.id,
        status=LoraStatus.TRAINING,
        storage_path="/data/audio/user_loras/u-a/x/lora",
        tensor_path="/data/audio/user_loras/u-a/x/lora/adapter.safetensors",
        training_job_id="job-xyz",
        error="transient",
        completed_at=completed,
        model_mode="turbo",
    )
    session.commit()
    fresh = get_user_lora(session, lora.id)
    assert fresh.status == LoraStatus.TRAINING
    assert fresh.storage_path.endswith("/lora")
    assert fresh.tensor_path.endswith("/adapter.safetensors")
    assert fresh.training_job_id == "job-xyz"
    assert fresh.error == "transient"
    assert fresh.completed_at is not None
    assert fresh.completed_at.replace(tzinfo=timezone.utc) == completed
    assert fresh.model_mode == "turbo"

    update_user_lora(session, lora.id, status=LoraStatus.READY, clear_error=True)
    session.commit()
    fresh = get_user_lora(session, lora.id)
    assert fresh.status == LoraStatus.READY
    assert fresh.error is None


def test_update_user_lora_missing_raises(session: Session) -> None:
    with pytest.raises(ValueError, match="UserLora not found"):
        update_user_lora(session, "does-not-exist", status=LoraStatus.READY)


def test_soft_delete_and_restore_user_lora(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "X", "x")
    session.commit()
    soft_delete_user_lora(session, lora.id)
    session.commit()
    assert get_user_lora(session, lora.id) is None

    restore_user_lora(session, lora.id)
    session.commit()
    assert get_user_lora(session, lora.id) is not None


def test_soft_delete_missing_raises(session: Session) -> None:
    with pytest.raises(ValueError):
        soft_delete_user_lora(session, "missing")
    with pytest.raises(ValueError):
        restore_user_lora(session, "missing")


def test_list_active_user_loras(session: Session) -> None:
    ready = create_user_lora(session, _USER_A, "Ready", "ready")
    queued = create_user_lora(session, _USER_A, "Queued", "queued")
    training = create_user_lora(session, _USER_A, "Training", "training")
    deleted_training = create_user_lora(session, _USER_A, "DelTr", "del-tr")
    session.commit()
    update_user_lora(session, ready.id, status=LoraStatus.READY)
    update_user_lora(session, queued.id, status=LoraStatus.QUEUED)
    update_user_lora(session, training.id, status=LoraStatus.TRAINING)
    update_user_lora(session, deleted_training.id, status=LoraStatus.TRAINING)
    session.commit()
    soft_delete_user_lora(session, deleted_training.id)
    session.commit()

    ids = {row.id for row in list_active_user_loras(session)}
    assert ids == {queued.id, training.id}


def test_list_active_user_loras_locks_only_reconcilable_candidates(session: Session) -> None:
    running = create_user_lora(session, _USER_A, "Running", "running")
    failed = create_user_lora(session, _USER_A, "Failed", "failed")
    missing = create_user_lora(session, _USER_A, "Missing", "missing")
    session.add_all([
        Job(id="running-job", type=JobType.LORA_TRAINING, status=JobStatus.RUNNING),
        Job(id="failed-job", type=JobType.LORA_TRAINING, status=JobStatus.FAILED),
    ])
    session.flush()
    update_user_lora(
        session, running.id, status=LoraStatus.TRAINING, training_job_id="running-job",
    )
    update_user_lora(
        session, failed.id, status=LoraStatus.TRAINING, training_job_id="failed-job",
    )
    update_user_lora(session, missing.id, status=LoraStatus.TRAINING)
    session.commit()

    candidates = list_active_user_loras(
        session, reconcilable_only=True, excluded_ids={failed.id}, limit=1,
    )

    assert [lora.id for lora in candidates] == [missing.id]


def test_add_sample_auto_positions(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "L", "l")
    session.commit()
    s1 = add_user_lora_sample(session, lora.id, "a/1.wav", caption="c1", lyrics="l1")
    s2 = add_user_lora_sample(session, lora.id, "a/2.wav", caption="c2", lyrics="l2")
    s3 = add_user_lora_sample(session, lora.id, "a/3.wav")
    session.commit()
    assert [s1.position, s2.position, s3.position] == [0, 1, 2]
    assert count_user_lora_samples(session, lora.id) == 3


def test_update_sample_caption_and_lyrics(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "L", "l")
    sample = add_user_lora_sample(session, lora.id, "a/1.wav")
    session.commit()

    update_user_lora_sample(session, sample.id, caption="new cap", lyrics="new ly")
    session.commit()
    fresh = get_user_lora_sample(session, sample.id)
    assert fresh.caption == "new cap"
    assert fresh.lyrics == "new ly"


def test_update_sample_missing_raises(session: Session) -> None:
    with pytest.raises(ValueError, match="UserLoraSample not found"):
        update_user_lora_sample(session, "missing", caption="x")


def test_reorder_sample_forward(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "L", "l")
    s1 = add_user_lora_sample(session, lora.id, "a/1.wav")
    s2 = add_user_lora_sample(session, lora.id, "a/2.wav")
    s3 = add_user_lora_sample(session, lora.id, "a/3.wav")
    session.commit()

    update_user_lora_sample(session, s1.id, position=2)
    session.commit()
    fresh_lora = get_user_lora(session, lora.id)
    positions = {s.id: s.position for s in fresh_lora.samples}
    assert positions[s2.id] == 0
    assert positions[s3.id] == 1
    assert positions[s1.id] == 2


def test_reorder_sample_backward_and_clamp(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "L", "l")
    s1 = add_user_lora_sample(session, lora.id, "a/1.wav")
    s2 = add_user_lora_sample(session, lora.id, "a/2.wav")
    s3 = add_user_lora_sample(session, lora.id, "a/3.wav")
    session.commit()

    update_user_lora_sample(session, s3.id, position=99)
    session.commit()
    fresh = get_user_lora(session, lora.id)
    positions = {s.id: s.position for s in fresh.samples}
    assert positions[s1.id] == 0
    assert positions[s2.id] == 1
    assert positions[s3.id] == 2

    update_user_lora_sample(session, s3.id, position=0)
    session.commit()
    fresh = get_user_lora(session, lora.id)
    positions = {s.id: s.position for s in fresh.samples}
    assert positions[s3.id] == 0
    assert positions[s1.id] == 1
    assert positions[s2.id] == 2


def test_delete_sample_returns_path_and_compacts(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "L", "l")
    s1 = add_user_lora_sample(session, lora.id, "a/1.wav")
    s2 = add_user_lora_sample(session, lora.id, "a/2.wav")
    s3 = add_user_lora_sample(session, lora.id, "a/3.wav")
    session.commit()

    path = delete_user_lora_sample(session, s2.id)
    session.commit()
    assert path == "a/2.wav"
    fresh = get_user_lora(session, lora.id)
    positions = {s.id: s.position for s in fresh.samples}
    assert positions == {s1.id: 0, s3.id: 1}


def test_delete_sample_missing_raises(session: Session) -> None:
    with pytest.raises(ValueError, match="UserLoraSample not found"):
        delete_user_lora_sample(session, "missing")


def test_samples_cascade_delete_when_lora_hard_deleted(session: Session) -> None:
    lora = create_user_lora(session, _USER_A, "L", "l")
    s1 = add_user_lora_sample(session, lora.id, "a/1.wav")
    session.commit()
    session.delete(lora)
    session.commit()
    assert get_user_lora_sample(session, s1.id) is None


def test_unique_slug_per_user(session: Session) -> None:
    create_user_lora(session, _USER_A, "V", "voice")
    session.commit()
    create_user_lora(session, _USER_B, "V", "voice")
    session.commit()

    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        create_user_lora(session, _USER_A, "V2", "voice")
        session.commit()
