"""Takes, voices, conversations and presets refuse with a catalog key, and a foreign one reads
as a missing one."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.mcp_tool_table import ALICE, BOB
from support.mcp_world import McpWorld
from support.postgres_lock_harness import WAIT_SECONDS, StatementPause, in_thread, stop_workers
from support.web_app import (
    make_authenticated_user,
    make_router_app,
    make_router_ctx,
    refusal_body,
    web_client,
)

from songmaker_cli.db.models import (
    Album,
    AvailableModel,
    Conversation,
    Generation,
    Playlist,
    Song,
    User,
    UserLora,
    UserLoraSample,
    Version,
)
from songmaker_cli.words import Key

OWNER_ID = "owner"
STRANGER_ID = "stranger"
MISSING_ID = "no-such-id"
TAKE_JUDGEMENTS = [
    ("get", "/api/generations/{}", {}),
    ("post", "/api/generations/{}/rate", {"json": {"rating": 80}}),
    ("post", "/api/generations/{}/pick", {}),
    ("post", "/api/generations/{}/unpick", {}),
    ("post", "/api/generations/{}/keep", {}),
    ("post", "/api/generations/{}/unkeep", {}),
    ("post", "/api/generations/{}/share", {}),
    ("delete", "/api/generations/{}/share", {}),
    ("delete", "/api/generations/{}", {}),
]


@pytest.fixture
def world(tmp_path: Path, pg_factory) -> dict[str, TestClient]:
    """The owner's takes, voices and conversation, with a client for each of two musicians."""
    ctx = make_router_ctx(tmp_path, db=pg_factory)
    audio = ctx.audio_dir / OWNER_ID
    audio.mkdir(parents=True)
    (audio / "take.mp3").write_bytes(b"audio")
    (audio / "folder.mp3").mkdir()
    (ctx.audio_dir.parent / "outside.mp3").write_bytes(b"audio")
    with pg_factory() as session:
        for user_id in (OWNER_ID, STRANGER_ID):
            session.add(User(id=user_id, username=user_id, role="user"))
        session.flush()
        session.add(Album(id="album", title="Album", artist="Band", created_by=OWNER_ID))
        session.add(Song(id="song", title="Song", album_id="album", slug="song"))
        session.add(Version(id="version", song_id="song", version_number=1))
        for number, (take_id, stored_path) in enumerate((
            ("take", f"{OWNER_ID}/take.mp3"), ("take-without-file", f"{OWNER_ID}/gone.mp3"),
            ("take-on-a-folder", f"{OWNER_ID}/folder.mp3"), ("take-outside", "../outside.mp3"),
        ), start=1):
            session.add(Generation(
                id=take_id, song_id="song", version_id="version", generation_number=number,
                mp3_path=stored_path,
            ))
        session.add(
            Album(id="stranger-album", title="Theirs", artist="Band", created_by=STRANGER_ID),
        )
        session.add(Song(id="stranger-song", title="Theirs", album_id="stranger-album", slug="s"))
        session.add(Version(id="stranger-version", song_id="stranger-song", version_number=1))
        session.add(Generation(
            id="stranger-take", song_id="stranger-song", version_id="stranger-version",
            generation_number=1, mp3_path=f"{STRANGER_ID}/take.mp3",
        ))
        session.add(Playlist(id="playlist", title="Mix", slug="mix", created_by=OWNER_ID))
        session.add(Conversation(id="conversation", user_id=OWNER_ID, title="Chat"))
        for lora_id, user_id in (("lora", OWNER_ID), ("other-lora", OWNER_ID),
                                 ("stranger-lora", STRANGER_ID)):
            session.add(UserLora(id=lora_id, user_id=user_id, name=lora_id, slug=lora_id))
        session.flush()
        for sample_id, lora_id in (("sample", "lora"), ("other-sample", "other-lora"),
                                   ("stranger-sample", "stranger-lora")):
            session.add(UserLoraSample(
                id=sample_id, user_lora_id=lora_id, audio_path=f"{sample_id}.wav",
                caption="c", lyrics="l", position=0,
            ))
        session.commit()
    return {
        user_id: web_client(
            make_router_app(ctx, user=make_authenticated_user(user_id, username=user_id)),
        )
        for user_id in (OWNER_ID, STRANGER_ID)
    }


@pytest.mark.parametrize(
    ("method", "path", "arguments"), TAKE_JUDGEMENTS,
    ids=[f"{method} {path}" for method, path, _ in TAKE_JUDGEMENTS],
)
def test_a_foreign_take_answers_the_body_of_a_missing_one(
    world: dict[str, TestClient], method: str, path: str, arguments: dict,
) -> None:
    stranger = world[STRANGER_ID]

    foreign = getattr(stranger, method)(path.format("take"), **arguments)
    missing = getattr(stranger, method)(path.format(MISSING_ID), **arguments)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == refusal_body("generationRefusal.notFound")
    assert foreign.json()["detail"] == "Generation not found"


def _after_the_take_is_read(statement: str) -> bool:
    return "FROM generations" in statement


@pytest.mark.parametrize(
    ("method", "path", "arguments"),
    [
        ("post", "/api/generations/take/rate", {"json": {"rating": 80}}),
        ("post", "/api/generations/take/pick", {}),
        ("post", "/api/generations/take/keep", {}),
        ("post", "/api/generations/take/share", {}),
        ("delete", "/api/generations/take/share", {}),
        ("delete", "/api/generations/take", {}),
        ("post", "/api/playlists/playlist/entries/generation",
         {"json": {"generation_id": "take"}}),
    ],
    ids=["rate", "pick", "keep", "share", "unshare", "delete", "playlist-add"],
)
def test_a_take_deleted_after_the_access_check_reads_like_a_missing_one(
    world: dict[str, TestClient], pg_factory, method: str, path: str, arguments: dict,
) -> None:
    pause = StatementPause(_after_the_take_is_read)
    answers: dict[str, object] = {}
    request = in_thread(answers, "request", lambda: getattr(world[OWNER_ID], method)(
        path, **arguments,
    ))
    pause.install(pg_factory)
    try:
        request.start()
        assert pause.reached.wait(WAIT_SECONDS), "The request never read the take"
        with pg_factory() as deleter:
            deleter.delete(deleter.get(Generation, "take"))
            deleter.commit()
    finally:
        pause.release.set()
        assert not stop_workers(pg_factory, (request,), (pause.backend_pid,))
        pause.remove(pg_factory)

    response = answers["request"]
    assert not isinstance(response, BaseException), response
    assert response.status_code == 404
    assert response.json() == refusal_body("generationRefusal.notFound")


@pytest.mark.parametrize("foreign_id", ["stranger-take", "no-such-id"])
def test_a_bulk_delete_with_one_foreign_or_missing_take_names_none(
    world: dict[str, TestClient], foreign_id: str,
) -> None:
    response = world[OWNER_ID].post(
        "/api/generations/bulk-delete", json={"generation_ids": ["take", foreign_id]},
    )

    assert response.status_code == 404
    assert response.json() == refusal_body("generationRefusal.someNotFound")
    assert response.json()["detail"] == "One or more generations not found"


@pytest.mark.parametrize(
    ("method", "path", "arguments"),
    [
        ("get", "/api/loras/{}", {}),
        ("delete", "/api/loras/{}", {}),
        ("post", "/api/loras/{}/samples/from-generation", {"json": {"generation_id": "take"}}),
    ],
    ids=["get", "delete", "add-sample-from-take"],
)
def test_a_foreign_voice_answers_the_body_of_a_missing_one(
    world: dict[str, TestClient], method: str, path: str, arguments: dict,
) -> None:
    stranger = world[STRANGER_ID]

    foreign = getattr(stranger, method)(path.format("lora"), **arguments)
    missing = getattr(stranger, method)(path.format(MISSING_ID), **arguments)

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == refusal_body("voiceRefusal.notFound")
    assert foreign.json()["detail"] == "LoRA not found"


def test_a_generation_names_a_foreign_deleted_or_missing_voice_as_not_found(
    world: dict[str, TestClient], pg_factory,
) -> None:
    stranger = world[STRANGER_ID]
    world[OWNER_ID].delete("/api/loras/lora")
    answers = []

    for voice_id in ("lora", "other-lora", MISSING_ID):
        with pg_factory() as session:
            version = session.get(Version, "stranger-version")
            version.lyrics, version.prompt = "la", "pop"
            version.generation_params = {"user_lora_id": voice_id}
            session.get(AvailableModel, "turbo").is_active = True
            session.commit()
        answers.append(
            stranger.post("/api/songs/stranger-song/generate", json={"model": "turbo"}),
        )

    assert [answer.status_code for answer in answers] == [404] * 3
    assert [answer.json() for answer in answers] == [refusal_body("voiceRefusal.notFound")] * 3


@pytest.mark.parametrize("verb", ["patch", "delete"])
@pytest.mark.parametrize(
    "sample_id",
    ["stranger-sample", "other-sample", MISSING_ID],
    ids=["foreign", "of-another-voice", "missing"],
)
def test_a_sample_the_person_cannot_reach_answers_the_body_of_a_missing_one(
    world: dict[str, TestClient], verb: str, sample_id: str,
) -> None:
    arguments = {"json": {"caption": "x"}} if verb == "patch" else {}

    response = getattr(world[OWNER_ID], verb)(f"/api/loras/lora/samples/{sample_id}", **arguments)

    assert response.status_code == 404
    assert response.json() == refusal_body("voiceRefusal.sampleNotFound")
    assert response.json()["detail"] == "LoRA sample not found"


@pytest.mark.parametrize(
    ("take_id", "key"),
    [
        ("take-without-file", "generationRefusal.audioMissing"),
        ("take-outside", "generationRefusal.audioMissing"),
        ("take-on-a-folder", "generationRefusal.notFound"),
        (MISSING_ID, "generationRefusal.notFound"),
    ],
)
def test_adding_a_sample_from_a_take_without_a_usable_file_names_the_take_or_its_file(
    world: dict[str, TestClient], take_id: str, key: Key,
) -> None:
    response = world[OWNER_ID].post(
        "/api/loras/lora/samples/from-generation", json={"generation_id": take_id},
    )

    assert response.status_code == 404
    assert response.json() == refusal_body(key)


def test_a_foreign_take_added_as_a_sample_answers_the_body_of_a_missing_take(
    world: dict[str, TestClient],
) -> None:
    stranger = world[STRANGER_ID]

    foreign = stranger.post(
        "/api/loras/stranger-lora/samples/from-generation", json={"generation_id": "take"},
    )
    missing = stranger.post(
        "/api/loras/stranger-lora/samples/from-generation", json={"generation_id": MISSING_ID},
    )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == refusal_body("generationRefusal.notFound")


def test_a_foreign_conversation_answers_the_body_of_a_missing_one(
    world: dict[str, TestClient],
) -> None:
    stranger = world[STRANGER_ID]

    foreign = stranger.get("/api/conversations/conversation")
    missing = stranger.get(f"/api/conversations/{MISSING_ID}")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == refusal_body("conversationRefusal.notFound")
    assert foreign.json()["detail"] == "Conversation not found"


def test_a_persons_own_agent_reads_a_foreign_take_and_conversation_like_missing_ones(
    household: McpWorld,
) -> None:
    for tool, argument, foreign_id, missing_id, key in (
        ("get_take", "gen_id", f"take-{BOB}", f"take-{ALICE}-missing",
         "generationRefusal.notFound"),
        ("get_conversation", "conversation_id", f"conversation-{BOB}",
         f"conversation-{ALICE}-missing", "conversationRefusal.notFound"),
    ):
        foreign = household.call(tool, {argument: foreign_id})
        missing = household.call(tool, {argument: missing_id})

        assert foreign.is_error
        assert missing.is_error
        assert foreign.json() == missing.json() == refusal_body(key)
