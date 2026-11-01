"""POST /api/references through the full middleware stack."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from support.token_world import TokenWorld, make_token_world
from support.wav_files import write_wav
from support.web_app import TEST_ORIGIN, make_test_app, seed_session

from songmaker_cli.constants import (
    AUDIO_UPLOAD_BODY_MAX_BYTES,
    AUDIO_UPLOAD_FILE_MAX_BYTES,
)
from songmaker_cli.db.models import ReferenceRecording, User
from songmaker_cli.db.queries.reference_recordings import create_reference_recording
from songmaker_cli.settings import get_settings

REFERENCES_PATH = "/api/references"
WAV_BYTES = b"RIFF" + b"\x00" * 200
MPEG_FRAME_BYTES = 417  # MPEG-1 layer III, 128 kbit/s, 44.1 kHz
MPEG_FRAME_COUNT = 40


def _seed_reference_owner(session) -> None:
    session.add(User(id="owner-id", username="owner"))


@pytest.fixture
def signed_in(tmp_path: Path) -> TestClient:
    client, _ = make_test_app(tmp_path, seed_db=_seed_reference_owner)
    seed_session(client, "owner")
    return client


def _one_second_wav_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "tone.wav"
    write_wav(path, np.zeros(8000, dtype=np.float32), 8000)
    return path.read_bytes()


def _repeated_mpeg_frames() -> bytes:
    frame = b"\xff\xfb\x90\x00".ljust(MPEG_FRAME_BYTES, b"\x00")
    return frame * MPEG_FRAME_COUNT


def _reference_rows(client: TestClient) -> list[ReferenceRecording]:
    with client.app.state.ctx.db() as session:
        return session.query(ReferenceRecording).all()


def _reference_files(client: TestClient) -> list[Path]:
    return [path for path in client.app.state.ctx.audio_dir.rglob("*") if path.is_file()]


def _post_reference(
    client: TestClient, payload: bytes = WAV_BYTES, name: str = "ref.wav", **kwargs,
):
    return client.post(REFERENCES_PATH, files={"file": (name, payload, "audio/wav")}, **kwargs)


def _without_fetch_metadata(signed_in: TestClient) -> TestClient:
    """A client that adds no Fetch Metadata, carrying the signed-in cookies."""
    return TestClient(
        signed_in.app, base_url=TEST_ORIGIN, cookies=signed_in.cookies,
        raise_server_exceptions=False,
    )


@pytest.mark.parametrize("kind", ["wav", "mp3"])
def test_m1_an_upload_answers_the_stored_record(
    signed_in: TestClient, tmp_path: Path, kind: str,
) -> None:
    payload = _one_second_wav_bytes(tmp_path) if kind == "wav" else _repeated_mpeg_frames()

    response = _post_reference(signed_in, payload, f"ref.{kind}")

    assert response.status_code == 200, response.text
    [row] = _reference_rows(signed_in)
    body = response.json()
    assert set(body) == {"id", "filename", "size_bytes", "duration_sec", "created_at"}
    assert body["id"] == row.id
    assert body["filename"] == row.original_filename == f"ref.{kind}"
    assert body["size_bytes"] == len(payload) == row.size_bytes
    assert row.duration_sec is not None
    assert body["duration_sec"] == row.duration_sec
    assert datetime.fromisoformat(body["created_at"]) == row.created_at
    assert (signed_in.app.state.ctx.audio_dir / row.storage_path).read_bytes() == payload


def test_m2_a_directory_part_in_the_client_name_is_dropped(signed_in: TestClient) -> None:
    response = _post_reference(signed_in, name="../../etc/dir/song.wav")

    assert response.status_code == 200
    assert response.json()["filename"] == "song.wav"


@pytest.mark.parametrize(
    ("payload", "name"),
    [
        pytest.param(WAV_BYTES, "a" * 252 + ".wav", id="over-long-name"),
        pytest.param(WAV_BYTES, "ref.txt", id="bad-extension"),
        pytest.param(b"tiny", "ref.wav", id="under-100-bytes"),
    ],
)
def test_m3_an_invalid_upload_is_refused_and_stores_nothing(
    signed_in: TestClient, payload: bytes, name: str,
) -> None:
    response = _post_reference(signed_in, payload, name)

    assert response.status_code == 400
    assert _reference_rows(signed_in) == []
    assert _reference_files(signed_in) == []


def test_m3_an_upload_without_a_filename_is_refused(signed_in: TestClient) -> None:
    boundary = "emptyfilename"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename=""\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode() + WAV_BYTES + f"\r\n--{boundary}--\r\n".encode()

    response = signed_in.post(
        REFERENCES_PATH,
        content=body,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 400
    assert "filename" in response.json()["detail"].lower()
    assert _reference_rows(signed_in) == []
    assert _reference_files(signed_in) == []


def test_m4a_a_file_of_the_size_limit_inside_the_envelope_is_accepted(
    signed_in: TestClient,
) -> None:
    response = _post_reference(signed_in, b"RIFF" + b"\x00" * (AUDIO_UPLOAD_FILE_MAX_BYTES - 4))

    assert response.status_code == 200, response.text


def test_m4b_a_file_just_over_the_size_limit_is_refused_and_stores_nothing(
    signed_in: TestClient,
) -> None:
    response = _post_reference(signed_in, b"RIFF" + b"\x00" * (AUDIO_UPLOAD_FILE_MAX_BYTES - 3))

    assert response.status_code == 400
    assert "too large" in response.json()["detail"].lower()
    assert _reference_rows(signed_in) == []
    assert _reference_files(signed_in) == []


@pytest.mark.parametrize("with_session", [True, False])
def test_m4c_a_body_over_the_allowance_is_refused_before_authentication(
    signed_in: TestClient, with_session: bool,
) -> None:
    client = _without_fetch_metadata(signed_in) if with_session else TestClient(
        signed_in.app, base_url=TEST_ORIGIN, raise_server_exceptions=False,
    )
    response = client.post(
        REFERENCES_PATH,
        content=b"x" * (AUDIO_UPLOAD_BODY_MAX_BYTES + 1),
        headers={"content-type": "application/octet-stream", "Sec-Fetch-Site": "same-origin"},
    )

    assert response.status_code == 413
    assert _reference_rows(signed_in) == []
    assert _reference_files(signed_in) == []


@pytest.mark.parametrize("fullness", ["files", "bytes"])
def test_m5_a_full_quota_refuses_with_409_and_stores_nothing(
    signed_in: TestClient, fullness: str,
) -> None:
    settings = get_settings()
    count = settings.reference_audio_quota_files if fullness == "files" else 1
    size = settings.reference_audio_quota_bytes if fullness == "bytes" else 1
    with signed_in.app.state.ctx.db() as session:
        for index in range(count):
            create_reference_recording(
                session, user_id="owner-id", storage_path=f"owner-id/refs/seed-{index}.wav",
                original_filename=f"seed-{index}.wav", size_bytes=size, duration_sec=None,
            )
        session.commit()

    response = _post_reference(signed_in)

    assert response.status_code == 409
    assert len(_reference_rows(signed_in)) == count
    assert _reference_files(signed_in) == []


def test_m6_the_former_upload_path_is_gone(signed_in: TestClient) -> None:
    response = signed_in.post(
        "/api/audio/upload", files={"file": ("ref.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 404
    assert _reference_rows(signed_in) == []
    assert _reference_files(signed_in) == []


def test_m7a_a_same_origin_cookie_upload_belongs_to_the_signed_in_person(
    signed_in: TestClient,
) -> None:
    response = _post_reference(signed_in)

    assert response.status_code == 200
    [row] = _reference_rows(signed_in)
    assert row.user_id == "owner-id"


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({"Origin": "https://foreign.example"}, id="other-site"),
        pytest.param({}, id="no-origin-proof"),
    ],
)
def test_m7b_a_cookie_upload_without_origin_proof_is_refused(
    signed_in: TestClient, headers: dict[str, str],
) -> None:
    response = _post_reference(_without_fetch_metadata(signed_in), headers=headers)

    assert response.status_code == 403
    assert _reference_rows(signed_in) == []
    assert _reference_files(signed_in) == []


def test_m7c_no_session_with_origin_proof_is_unauthenticated(signed_in: TestClient) -> None:
    anonymous = TestClient(
        signed_in.app, base_url=TEST_ORIGIN, raise_server_exceptions=False,
    )
    response = _post_reference(anonymous, headers={"Sec-Fetch-Site": "same-origin"})

    assert response.status_code == 401
    assert _reference_rows(signed_in) == []
    assert _reference_files(signed_in) == []


def test_m7d_a_persons_token_without_origin_uploads_as_that_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = make_token_world(tmp_path)

    response = _post_reference(world.client, headers=world.bearer(TokenWorld.ALICE))

    assert response.status_code == 200, response.text
    assert world.rows(ReferenceRecording, "user_id") == [(TokenWorld.ALICE,)]
