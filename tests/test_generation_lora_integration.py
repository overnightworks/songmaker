"""Integration tests: user_lora_id flows from request → version → config."""

from __future__ import annotations

from pathlib import Path

import pytest

from songmaker_cli.api_helpers import check_lora_ready_for_generation
from songmaker_cli.api_models.generation_params import (
    BaseGenerationParams,
    StoredGenerationParams,
)
from songmaker_cli.constants import LoraStatus
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Song, User, UserLora, Version
from songmaker_cli.db.queries import create_user_lora, update_user_lora
from songmaker_cli.jobs.generation import (
    _apply_user_lora_path,
    _extract_user_lora_id,
)
from songmaker_cli.middleware import AuthenticatedUser

USER_A = "u-alice"
USER_B = "u-bob"


def _auth(user_id: str = USER_A, role: str = "user") -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id, username=user_id, role=role, is_active=True,
    )


@pytest.fixture()
def db_factory(tmp_path: Path):
    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id=USER_A, username="alice", password_hash="x"))
        session.add(User(id=USER_B, username="bob", password_hash="x"))
        session.commit()
    return factory


def _make_ready_lora(
    db_factory, user_id: str, storage_path: str = "user_loras/u/l/lora",
) -> str:
    with db_factory() as session:
        lora = create_user_lora(session, user_id, "voice", "voice")
        update_user_lora(
            session, lora.id, status=LoraStatus.READY, storage_path=storage_path,
        )
        session.commit()
        return lora.id


def test_user_lora_id_accepted_on_base_generation_params() -> None:
    params = BaseGenerationParams.model_validate({"user_lora_id": "abc-123"})
    assert params.user_lora_id == "abc-123"


def test_user_lora_id_persisted_on_stored_generation_params() -> None:
    stored = StoredGenerationParams(user_lora_id="abc-123", bpm=120)
    dumped = stored.model_dump(exclude_none=True)
    assert dumped["user_lora_id"] == "abc-123"


def test_extract_user_lora_id_from_pydantic() -> None:
    params = BaseGenerationParams(user_lora_id="L")
    assert _extract_user_lora_id(params) == "L"


def test_extract_user_lora_id_from_dict() -> None:
    assert _extract_user_lora_id({"user_lora_id": "L"}) == "L"


def test_extract_user_lora_id_from_none() -> None:
    assert _extract_user_lora_id(None) is None


def test_extract_user_lora_id_from_invalid() -> None:
    assert _extract_user_lora_id({"not_a_field": 1, "user_lora_id": 42}) is None


def test_check_lora_ready_accepts_ready_lora(db_factory) -> None:
    lora_id = _make_ready_lora(db_factory, USER_A)
    with db_factory() as session:
        lora = check_lora_ready_for_generation(session, lora_id, _auth(USER_A))
        assert lora is not None
        assert lora.id == lora_id


def test_check_lora_ready_none_is_noop(db_factory) -> None:
    with db_factory() as session:
        assert check_lora_ready_for_generation(session, None, _auth(USER_A)) is None


def test_check_lora_ready_rejects_non_ready(db_factory) -> None:
    from fastapi import HTTPException

    with db_factory() as session:
        lora = create_user_lora(session, USER_A, "x", "x")
        lora_id = lora.id
        session.commit()

    with db_factory() as session:
        with pytest.raises(HTTPException) as exc:
            check_lora_ready_for_generation(session, lora_id, _auth(USER_A))
    assert exc.value.status_code == 422


def test_check_lora_ready_rejects_deleted(db_factory) -> None:
    from datetime import datetime, timezone

    from fastapi import HTTPException

    lora_id = _make_ready_lora(db_factory, USER_A)
    with db_factory() as session:
        lora = session.query(UserLora).filter_by(id=lora_id).first()
        lora.deleted_at = datetime.now(timezone.utc)
        session.commit()
    with db_factory() as session:
        with pytest.raises(HTTPException) as exc:
            check_lora_ready_for_generation(session, lora_id, _auth(USER_A))
    assert exc.value.status_code == 422


def test_check_lora_ready_rejects_cross_user(db_factory) -> None:
    from fastapi import HTTPException

    lora_id = _make_ready_lora(db_factory, USER_A)
    with db_factory() as session:
        with pytest.raises(HTTPException) as exc:
            check_lora_ready_for_generation(session, lora_id, _auth(USER_B))
    assert exc.value.status_code == 404


def test_check_lora_ready_admin_cannot_access_another_users_lora(db_factory) -> None:
    from fastapi import HTTPException

    lora_id = _make_ready_lora(db_factory, USER_A)
    with db_factory() as session:
        with pytest.raises(HTTPException) as exc:
            check_lora_ready_for_generation(
                session, lora_id, _auth(USER_B, role="admin"),
            )
    assert exc.value.status_code == 404


def test_check_lora_ready_404_when_missing(db_factory) -> None:
    from fastapi import HTTPException

    with db_factory() as session:
        with pytest.raises(HTTPException) as exc:
            check_lora_ready_for_generation(
                session, "does-not-exist", _auth(USER_A),
            )
    assert exc.value.status_code == 404


def test_apply_user_lora_path_injects_absolute_path(db_factory, tmp_path) -> None:
    from acestep_engine.models import AceStepConfig

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    lora_id = _make_ready_lora(db_factory, USER_A, "user_loras/alice/L/lora")
    params = BaseGenerationParams(user_lora_id=lora_id)
    config = AceStepConfig(prompt="p", lyrics="L")
    result = _apply_user_lora_path(config, params, db_factory, audio_dir)
    assert result.lora_path.endswith("user_loras/alice/L/lora")


def test_apply_user_lora_path_skips_when_not_ready(db_factory, tmp_path) -> None:
    from acestep_engine.models import AceStepConfig

    with db_factory() as session:
        lora = create_user_lora(session, USER_A, "x", "x")
        lora_id = lora.id
        session.commit()

    params = BaseGenerationParams(user_lora_id=lora_id)
    config = AceStepConfig(prompt="p", lyrics="L")
    result = _apply_user_lora_path(config, params, db_factory, tmp_path / "audio")
    assert result.lora_path == ""


def test_apply_user_lora_path_noop_when_none(db_factory, tmp_path) -> None:
    from acestep_engine.models import AceStepConfig

    params = BaseGenerationParams()
    config = AceStepConfig(prompt="p", lyrics="L")
    result = _apply_user_lora_path(config, params, db_factory, tmp_path / "audio")
    assert result is config


def test_generate_endpoint_rejects_foreign_lora_for_admin(tmp_path) -> None:
    from conftest import TEST_SECRET, make_fake_redis
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from songmaker_cli.api import router
    from songmaker_cli.app_context import AppContext
    from songmaker_cli.middleware import get_current_user

    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    factory = init_test_db(tmp_path / "test.db")
    with factory() as session:
        session.add(User(id=USER_A, username="alice", password_hash="x"))
        session.add(User(id=USER_B, username="bob", password_hash="x", role="admin"))
        session.flush()
        lora = create_user_lora(session, USER_A, "voice", "voice")
        update_user_lora(
            session, lora.id, status=LoraStatus.READY, storage_path="user_loras/alice/voice",
        )
        session.add(Album(id="A1", title="A", artist="a", created_by=USER_A))
        session.flush()
        session.add(
            Song(id="S1", title="S", album_id="A1", track_number=1),
        )
        session.flush()
        session.add(
            Version(
                id="V1", song_id="S1", version_number=1,
                lyrics="la", prompt="pop", bpm=120, audio_duration=30,
                generation_params={"user_lora_id": lora.id},
            ),
        )
        session.commit()

    ctx = AppContext(
        db=factory, audio_dir=audio_dir, data_dir=tmp_path / "data",
        session_secret=TEST_SECRET, redis=make_fake_redis(),
    )
    (tmp_path / "data").mkdir()
    app = FastAPI()
    app.state.ctx = ctx
    app.dependency_overrides[get_current_user] = lambda: _auth(USER_B, role="admin")
    app.include_router(router)
    client = TestClient(app)

    resp = client.post("/api/songs/S1/generate", json={"count": 1, "model": "sft"})
    assert resp.status_code == 404
