"""POST and GET /api/references through the full middleware stack."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from support import reference_api_world
from support.reference_api_world import (
    AUDIO_BYTES,
    LINKS,
    NOT_FOUND,
    REFERENCES_PATH,
    SECRET_FILENAME,
    WAV_BYTES,
    link_reference,
    post_reference,
    reference_files,
    reference_rows,
    seed_playable,
    seed_reference,
    signed_in_as,
)
from support.token_world import TokenWorld, make_token_world
from support.wav_files import write_wav
from support.web_app import TEST_ORIGIN, web_client

from songmaker_cli import reference_api
from songmaker_cli.constants import (
    AUDIO_MEDIA_TYPES,
    AUDIO_UPLOAD_BODY_MAX_BYTES,
    AUDIO_UPLOAD_FILE_MAX_BYTES,
    REFERENCE_AUDIO_EXTENSIONS,
)
from songmaker_cli.db.models import (
    Base,
    ReferenceRecording,
)
from songmaker_cli.db.queries.reference_recordings import (
    REFERENCE_LINK_COLUMNS,
    create_reference_recording,
)
from songmaker_cli.settings import get_settings

signed_in = reference_api_world.signed_in

MPEG_FRAME_BYTES = 417  # MPEG-1 layer III, 128 kbit/s, 44.1 kHz
MPEG_FRAME_COUNT = 40


def _one_second_wav_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "tone.wav"
    write_wav(path, np.zeros(8000, dtype=np.float32), 8000)
    return path.read_bytes()


def _repeated_mpeg_frames() -> bytes:
    frame = b"\xff\xfb\x90\x00".ljust(MPEG_FRAME_BYTES, b"\x00")
    return frame * MPEG_FRAME_COUNT



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

    response = post_reference(signed_in, payload, f"ref.{kind}")

    assert response.status_code == 200, response.text
    [row] = reference_rows(signed_in)
    body = response.json()
    assert set(body) == {
        "id", "filename", "size_bytes", "duration_sec", "created_at", "in_use",
        "used_by_versions", "used_by_takes",
    }
    assert body["in_use"] is False
    assert (body["used_by_versions"], body["used_by_takes"]) == (0, 0)
    assert body["id"] == row.id
    assert body["filename"] == row.original_filename == f"ref.{kind}"
    assert body["size_bytes"] == len(payload) == row.size_bytes
    assert row.duration_sec is not None
    assert body["duration_sec"] == row.duration_sec
    assert datetime.fromisoformat(body["created_at"]) == row.created_at
    assert (signed_in.app.state.ctx.audio_dir / row.storage_path).read_bytes() == payload


@pytest.mark.parametrize(
    ("sent", "stored"),
    [("../../etc/dir/song.wav", "song.wav"), ("Würde é.wav", "Würde é.wav")],
)
def test_m2_a_directory_part_in_the_client_name_is_dropped_and_a_non_ascii_name_kept(
    signed_in: TestClient, sent: str, stored: str,
) -> None:
    response = post_reference(signed_in, name=sent)

    assert response.status_code == 200
    assert response.json()["filename"] == stored


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
    response = post_reference(signed_in, payload, name)

    assert response.status_code == 400
    assert reference_rows(signed_in) == []
    assert reference_files(signed_in) == []


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
    assert reference_rows(signed_in) == []
    assert reference_files(signed_in) == []


def test_m4a_a_file_of_the_size_limit_inside_the_envelope_is_accepted(
    signed_in: TestClient,
) -> None:
    response = post_reference(signed_in, b"RIFF" + b"\x00" * (AUDIO_UPLOAD_FILE_MAX_BYTES - 4))

    assert response.status_code == 200, response.text


def test_m4b_a_file_just_over_the_size_limit_is_refused_and_stores_nothing(
    signed_in: TestClient,
) -> None:
    response = post_reference(signed_in, b"RIFF" + b"\x00" * (AUDIO_UPLOAD_FILE_MAX_BYTES - 3))

    assert response.status_code == 400
    assert "too large" in response.json()["detail"].lower()
    assert reference_rows(signed_in) == []
    assert reference_files(signed_in) == []


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
    assert reference_rows(signed_in) == []
    assert reference_files(signed_in) == []


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

    response = post_reference(signed_in)

    assert response.status_code == 409
    assert len(reference_rows(signed_in)) == count
    assert reference_files(signed_in) == []


def test_m6_the_former_upload_path_is_gone(signed_in: TestClient) -> None:
    response = signed_in.post(
        "/api/audio/upload", files={"file": ("ref.wav", WAV_BYTES, "audio/wav")},
    )

    assert response.status_code == 404
    assert reference_rows(signed_in) == []
    assert reference_files(signed_in) == []


def test_m7a_a_same_origin_cookie_upload_belongs_to_the_signed_in_person(
    signed_in: TestClient,
) -> None:
    response = post_reference(signed_in)

    assert response.status_code == 200
    [row] = reference_rows(signed_in)
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
    response = post_reference(_without_fetch_metadata(signed_in), headers=headers)

    assert response.status_code == 403
    assert reference_rows(signed_in) == []
    assert reference_files(signed_in) == []


def test_m7c_no_session_with_origin_proof_is_unauthenticated(signed_in: TestClient) -> None:
    anonymous = TestClient(
        signed_in.app, base_url=TEST_ORIGIN, raise_server_exceptions=False,
    )
    response = post_reference(anonymous, headers={"Sec-Fetch-Site": "same-origin"})

    assert response.status_code == 401
    assert reference_rows(signed_in) == []
    assert reference_files(signed_in) == []


def test_m7d_a_persons_token_without_origin_uploads_as_that_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = make_token_world(tmp_path)

    response = post_reference(world.client, headers=world.bearer(TokenWorld.ALICE))

    assert response.status_code == 200, response.text
    assert world.rows(ReferenceRecording, "user_id") == [(TokenWorld.ALICE,)]



@pytest.mark.parametrize(
    ("username", "expected"),
    [("owner", ["mine.wav"]), ("other", ["theirs.wav"]), ("boss", ["boss.wav"])],
)
def test_l1_a_person_lists_only_their_own_references(
    signed_in: TestClient, username: str, expected: list[str],
) -> None:
    seed_reference(signed_in, "owner-id", "mine.wav")
    seed_reference(signed_in, "other-id", "theirs.wav")
    seed_reference(signed_in, "boss-id", "boss.wav")

    response = signed_in_as(signed_in, username).get(REFERENCES_PATH)

    assert response.status_code == 200
    assert [item["filename"] for item in response.json()["references"]] == expected


def test_l2_references_come_newest_first_and_one_instant_keeps_one_order(
    signed_in: TestClient,
) -> None:
    now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
    seed_reference(signed_in, "owner-id", "old.wav", created_at=now - timedelta(days=9))
    seed_reference(signed_in, "owner-id", "new.wav", created_at=now)
    seed_reference(signed_in, "owner-id", "tie-b.wav", created_at=now - timedelta(days=1),
                    reference_id="bbbb")
    seed_reference(signed_in, "owner-id", "tie-a.wav", created_at=now - timedelta(days=1),
                    reference_id="aaaa")

    listed = signed_in.get(REFERENCES_PATH).json()["references"]

    assert [item["filename"] for item in listed] == [
        "new.wav", "tie-a.wav", "tie-b.wav", "old.wav",
    ]


def test_l3_no_references_answers_an_empty_list(signed_in: TestClient) -> None:
    response = signed_in.get(REFERENCES_PATH)

    assert response.status_code == 200
    assert response.json()["references"] == []


def test_l4_a_reference_without_a_length_answers_null(signed_in: TestClient) -> None:
    seed_reference(signed_in, "owner-id", "unmeasured.wav", duration_sec=None)

    [item] = signed_in.get(REFERENCES_PATH).json()["references"]

    assert item["duration_sec"] is None


def _seed_sized_reference(client: TestClient, user_id: str, size_bytes: int, index: int) -> None:
    with client.app.state.ctx.db() as session:
        create_reference_recording(
            session, user_id=user_id, storage_path=f"{user_id}/refs/sized-{index}.wav",
            original_filename=f"sized-{index}.wav", size_bytes=size_bytes, duration_sec=None,
        )
        session.commit()


@pytest.mark.parametrize(
    ("owned_sizes", "foreign_sizes", "expected_files", "expected_bytes"),
    [([], [], 0, 0), ([30, 12], [], 2, 42), ([30, 12], [999], 2, 42), ([], [999], 0, 0)],
    ids=["no-rows", "some-rows", "foreign-rows-uncounted", "only-foreign-rows"],
)
def test_l6_usage_counts_what_admission_counts_for_the_caller_only(
    signed_in: TestClient, owned_sizes: list[int], foreign_sizes: list[int],
    expected_files: int, expected_bytes: int,
) -> None:
    for index, size in enumerate(owned_sizes):
        _seed_sized_reference(signed_in, "owner-id", size, index)
    for index, size in enumerate(foreign_sizes):
        _seed_sized_reference(signed_in, "other-id", size, index)

    usage = signed_in.get(REFERENCES_PATH).json()["usage"]

    assert (usage["files"], usage["bytes"]) == (expected_files, expected_bytes)


def test_l7_usage_answers_the_limits_the_settings_name(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REFERENCE_AUDIO_QUOTA_FILES", "7")
    monkeypatch.setenv("REFERENCE_AUDIO_QUOTA_BYTES", "123456")
    get_settings.cache_clear()

    usage = signed_in.get(REFERENCES_PATH).json()["usage"]

    assert (usage["file_limit"], usage["byte_limit"]) == (7, 123456)


def test_l5_listing_without_a_session_is_unauthenticated(signed_in: TestClient) -> None:
    anonymous = TestClient(signed_in.app, base_url=TEST_ORIGIN, raise_server_exceptions=False)

    response = anonymous.get(REFERENCES_PATH)

    assert response.status_code == 401



def _audio_path(reference_id: str) -> str:
    return f"{REFERENCES_PATH}/{reference_id}/audio"


@pytest.mark.parametrize("extension", sorted(REFERENCE_AUDIO_EXTENSIONS))
def test_p1_the_owner_plays_the_whole_file(signed_in: TestClient, extension: str) -> None:
    reference_id = seed_playable(signed_in, name=f"take{extension}")

    response = signed_in.get(_audio_path(reference_id))

    assert response.status_code == 200
    assert response.headers["content-type"] == AUDIO_MEDIA_TYPES[extension]
    assert response.content == AUDIO_BYTES


def test_p1b_the_database_connection_is_returned_before_the_file_is_sent(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_out_when_sending: list[int] = []
    engine = signed_in.app.state.ctx.db.kw["bind"]

    class RecordingFileResponse(reference_api.OpenedFileResponse):
        async def __call__(self, scope, receive, send) -> None:
            checked_out_when_sending.append(engine.pool.checkedout())
            await super().__call__(scope, receive, send)

    monkeypatch.setattr(reference_api, "OpenedFileResponse", RecordingFileResponse)

    signed_in.get(_audio_path(seed_playable(signed_in)))

    assert checked_out_when_sending == [0]


def test_p2_a_range_request_answers_a_partial_response(signed_in: TestClient) -> None:
    response = signed_in.get(
        _audio_path(seed_playable(signed_in)), headers={"Range": "bytes=0-99"},
    )

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 0-99/{len(AUDIO_BYTES)}"
    assert response.content == AUDIO_BYTES[:100]


@pytest.mark.parametrize(
    ("range_header", "status", "expected"),
    [
        ("bytes=1000-", 206, AUDIO_BYTES[1000:]),
        ("bytes=-50", 206, AUDIO_BYTES[-50:]),
        (f"bytes={10 * len(AUDIO_BYTES)}-", 416, None),
    ],
)
def test_p3_open_suffix_and_unsatisfiable_ranges(
    signed_in: TestClient, range_header: str, status: int, expected: bytes | None,
) -> None:
    response = signed_in.get(
        _audio_path(seed_playable(signed_in)), headers={"Range": range_header},
    )

    assert response.status_code == status
    if expected is not None:
        assert response.content == expected


def test_p4_another_person_gets_the_same_404_as_an_unknown_id(signed_in: TestClient) -> None:
    reference_id = seed_playable(signed_in)

    foreign = signed_in_as(signed_in, "other").get(_audio_path(reference_id))
    unknown = signed_in_as(signed_in, "other").get(_audio_path("no-such-id"))

    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json() == NOT_FOUND


def test_p5_an_admin_cannot_play_another_persons_reference(signed_in: TestClient) -> None:
    response = signed_in_as(signed_in, "boss").get(_audio_path(seed_playable(signed_in)))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_p6_an_unknown_id_is_not_found(signed_in: TestClient) -> None:
    response = signed_in.get(_audio_path("no-such-id"))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_p7_a_row_whose_file_is_gone_is_not_found_and_logs_no_name_or_path(
    signed_in: TestClient, caplog: pytest.LogCaptureFixture,
) -> None:
    reference_id = seed_playable(signed_in)
    for path in reference_files(signed_in):
        path.unlink()
    audio_dir = str(signed_in.app.state.ctx.audio_dir)

    with caplog.at_level(logging.ERROR):
        response = signed_in.get(_audio_path(reference_id))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert "owner-id" in message
    assert reference_id in message
    assert "ReferenceAudioRejected" in message
    assert SECRET_FILENAME not in message
    assert audio_dir not in message
    assert errors[0].exc_info is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root opens a file whatever its mode")
def test_p7b_a_file_that_cannot_be_opened_is_not_found_and_logs_no_name_or_path(
    signed_in: TestClient, caplog: pytest.LogCaptureFixture,
) -> None:
    reference_id = seed_playable(signed_in)
    (unreadable,) = reference_files(signed_in)
    unreadable.chmod(0)
    audio_dir = str(signed_in.app.state.ctx.audio_dir)

    with caplog.at_level(logging.ERROR):
        response = signed_in.get(_audio_path(reference_id))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 1
    message = errors[0].getMessage()
    assert SECRET_FILENAME not in message
    assert audio_dir not in message
    assert errors[0].exc_info is None


def test_p8_a_symlink_leaf_out_of_the_root_is_not_found(
    signed_in: TestClient, tmp_path: Path,
) -> None:
    reference_id = seed_playable(signed_in)
    leaf = signed_in.app.state.ctx.audio_dir / "owner-id" / "refs" / SECRET_FILENAME
    outside = tmp_path / "outside.wav"
    outside.write_bytes(AUDIO_BYTES)
    leaf.unlink()
    leaf.symlink_to(outside)

    response = signed_in.get(_audio_path(reference_id))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND


def test_p9a_without_a_session_the_audio_is_unauthenticated(signed_in: TestClient) -> None:
    reference_id = seed_playable(signed_in)
    anonymous = TestClient(signed_in.app, base_url=TEST_ORIGIN, raise_server_exceptions=False)

    assert anonymous.get(_audio_path(reference_id)).status_code == 401


def test_p9b_a_persons_token_plays_that_persons_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKEN_CLIENTS", TokenWorld.HAL)
    world = make_token_world(tmp_path)
    uploaded = post_reference(
        world.client, AUDIO_BYTES, "mine.wav", headers=world.bearer(TokenWorld.ALICE),
    )
    reference_id = uploaded.json()["id"]

    response = world.client.get(_audio_path(reference_id), headers=world.bearer(TokenWorld.ALICE))

    assert response.status_code == 200, response.text
    assert response.content == AUDIO_BYTES


@pytest.mark.parametrize("link", LINKS)
def test_l8_the_list_marks_a_linked_reference_as_in_use(
    signed_in: TestClient, link: dict,
) -> None:
    linked = seed_reference(signed_in, "owner-id", "linked.wav")
    seed_reference(signed_in, "owner-id", "free.wav")
    link_reference(signed_in, linked, **link)

    listed = signed_in.get(REFERENCES_PATH).json()["references"]

    assert {item["filename"]: item["in_use"] for item in listed} == {
        "linked.wav": True, "free.wav": False,
    }
    counts = {
        item["filename"]: (item["used_by_versions"], item["used_by_takes"]) for item in listed
    }
    assert counts == {
        "linked.wav": (1, 0) if link["via"] == "version" else (0, 1), "free.wav": (0, 0),
    }


def test_l9_the_in_use_query_checks_every_foreign_key_that_points_at_a_reference() -> None:
    referencing = {
        (foreign_key.parent.table.name, foreign_key.parent.name)
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == ReferenceRecording.__tablename__
    }

    checked = {
        (link.class_.__tablename__, link.property.columns[0].name)
        for link in REFERENCE_LINK_COLUMNS
    }

    assert checked == referencing


@pytest.mark.parametrize("control", ["\x00", "\x01", "\x09", "\x1b", "\x1f"])
def test_f1_a_filename_with_a_control_character_is_refused_and_stores_nothing(
    signed_in: TestClient, control: str,
) -> None:
    boundary = "controlname"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="re{control}f.wav"\r\nContent-Type: audio/wav\r\n\r\n'
    ).encode() + WAV_BYTES + f"\r\n--{boundary}--\r\n".encode()

    response = signed_in.post(
        REFERENCES_PATH,
        content=body,
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid filename."}
    assert reference_rows(signed_in) == []
    assert reference_files(signed_in) == []


def _vanish_after_the_route_checked_the_file(
    monkeypatch: pytest.MonkeyPatch, target: Path,
) -> None:
    real_fstat = os.fstat
    target_inode = target.stat().st_ino

    def fstat_then_vanish(descriptor: int) -> os.stat_result:
        result = real_fstat(descriptor)
        if result.st_ino == target_inode and target.exists():
            target.unlink()
        return result

    monkeypatch.setattr(os, "fstat", fstat_then_vanish)


def test_s1_a_file_vanishing_after_the_check_logs_the_kind_and_no_path(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    reference_id = seed_playable(signed_in)
    (target,) = reference_files(signed_in)
    audio_dir = str(signed_in.app.state.ctx.audio_dir)
    _vanish_after_the_route_checked_the_file(monkeypatch, target)
    client = web_client(signed_in.app, cookies=signed_in.cookies, raise_server_exceptions=False)

    with caplog.at_level(logging.DEBUG):
        response = client.get(_audio_path(reference_id))

    assert response.content != AUDIO_BYTES
    ended = [r for r in caplog.records if "ended while it was sent" in r.getMessage()]
    assert [r.getMessage().rsplit(": ", 1)[1] for r in ended] == ["FileNotFoundError"]
    assert SECRET_FILENAME not in caplog.text
    assert audio_dir not in caplog.text


def test_s1b_a_file_vanishing_after_the_headers_ends_the_body_without_an_escape(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / SECRET_FILENAME
    path.write_bytes(AUDIO_BYTES)
    response = reference_api.OpenedFileResponse(
        path, stat_result=path.stat(), media_type=AUDIO_MEDIA_TYPES[".wav"],
    )
    path.unlink()
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {"type": "http", "method": "GET", "headers": [], "extensions": {}}
    with caplog.at_level(logging.DEBUG):
        asyncio.run(response(scope, receive, send))

    assert [message["type"] for message in sent] == ["http.response.start"]
    assert sent[0]["status"] == 200
    assert SECRET_FILENAME not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_s2_a_file_gone_before_the_check_is_not_found(signed_in: TestClient) -> None:
    reference_id = seed_playable(signed_in)
    (target,) = reference_files(signed_in)
    target.unlink()

    response = signed_in.get(_audio_path(reference_id))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
