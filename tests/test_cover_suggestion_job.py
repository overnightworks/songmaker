"""Cover-suggestion music job and isolated Codex image-route tests."""

from __future__ import annotations

import asyncio
import json
import threading
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from songmaker_cli.agent_cli import CliRunOutcome, CliRunReason
from songmaker_cli.constants import (
    ALBUM_COVER_SUGGESTIONS_DIRNAME,
    COVER_PROMPT_MAX_CHARS,
    COVER_PROMPT_SONG_FIELD_MAX_CHARS,
    JOB_ERROR_COVER_CLI_LOGIN,
    JOB_ERROR_COVER_IMAGE_FAILED,
    JOB_ERROR_COVER_IMAGE_NOT_CREATED,
    JOB_ERROR_COVER_IMAGE_TOOL_BLOCKED,
    JobStatus,
    JobType,
)
from songmaker_cli.cowriter import codex_cli_adapter
from songmaker_cli.cowriter.catalog import ProviderSetupMethod
from songmaker_cli.cowriter.errors import (
    ProviderUnavailableError,
    SafeRouteReasonCode,
    normalize_route_failure,
)
from songmaker_cli.db.engine import init_test_db
from songmaker_cli.db.models import Album, Job, Song, User, Version
from songmaker_cli.jobs.cover_suggestions import build_cover_prompt, run_cover_suggestion_job

_REDACTED_CODEX_LOGIN = {
    "auth_mode": "chatgpt",
    "OPENAI_API_KEY": None,
    "last_refresh": "2026-09-04T19:20:00Z",
    "tokens": {
        "id_token": "id-token",
        "access_token": "access-token",
        "account_id": "account",
        "refresh_token": "",
    },
}
_FIXTURES = Path(__file__).parent / "fixtures"


def _png_bytes(*, size: tuple[int, int] = (300, 100)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (20, 80, 160)).save(output, format="PNG")
    return output.getvalue()


def _outcome(
    *,
    stdout: str = (
        '{"type":"thread.started"}\n'
        '{"type":"item.completed","item":{"type":"image_gen"}}\n'
        '{"type":"turn.completed","usage":{}}\n'
    ),
    stderr: str = "",
    complete: bool = True,
    reason: CliRunReason = CliRunReason.COMPLETE,
) -> CliRunOutcome:
    return CliRunOutcome(
        started=True,
        spawn_error=None,
        returncode=0,
        stdout=stdout,
        stderr=stderr,
        complete=complete,
        became_zombie=False,
        reason=reason,
    )


@pytest.fixture()
def cover_job(tmp_path: Path):
    factory = init_test_db(tmp_path / "songmaker.db")
    with factory() as session:
        user = User(id="u1", username="owner", password_hash="hash")
        session.add(user)
        session.flush()
        album = Album(id="album", title="A" * 200, artist="Artist", created_by=user.id)
        song = Song(id="song", album_id=album.id, title="Song", track_number=1)
        version = Version(
            id="version",
            song_id=song.id,
            version_number=1,
            prompt="p" * (COVER_PROMPT_SONG_FIELD_MAX_CHARS + 10),
            lyrics="l" * (COVER_PROMPT_SONG_FIELD_MAX_CHARS + 10),
        )
        job = Job(id="job", type=JobType.COVER, user_id=user.id, album_id=album.id)
        session.add_all([album, song, version, job])
        session.commit()
    return factory, tmp_path / "audio", "job"


def _install_fake_codex_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    outcome: CliRunOutcome | None = None,
    creates_artifact: bool = True,
) -> list[dict]:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({
        **_REDACTED_CODEX_LOGIN,
        "tokens": {
            **_REDACTED_CODEX_LOGIN["tokens"],
            "refresh_token": "renewal-secret",
        },
    }))
    calls: list[dict] = []

    def fake_runner(command, **kwargs):
        home = Path(kwargs["extra_env"]["CODEX_HOME"])
        calls.append({
            "command": command,
            "auth": (home / "auth.json").read_text(),
            **kwargs,
        })
        if creates_artifact:
            artifact = home / "generated_images" / "cover.png"
            artifact.parent.mkdir()
            artifact.write_bytes(_png_bytes())
        return outcome or _outcome()

    monkeypatch.setattr(codex_cli_adapter, "CODEX_CLI_AUTH_FILE", str(auth_file))
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", fake_runner)
    return calls


def test_cover_job_generates_three_normalized_pngs_through_isolated_fake_cli(
    cover_job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, audio_dir, job_id = cover_job
    calls = _install_fake_codex_cli(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "songmaker_cli.jobs.cover_suggestions.cover_image_provider_method",
        lambda: ProviderSetupMethod.CODEX_CLI,
    )

    asyncio.run(run_cover_suggestion_job(job_id, db_factory=factory, audio_dir=audio_dir))

    with factory() as session:
        job = session.get(Job, job_id)
        suggestions = sorted(job.album.cover_suggestions, key=lambda item: item.id)
        assert job.status == JobStatus.COMPLETED
        assert job.progress == 1.0
        assert len(suggestions) == 3
        paths = [item.png_path for item in suggestions]
    assert len(calls) == 3
    assert all(call["command"] == codex_cli_adapter._build_codex_image_command() for call in calls)
    assert all(call["stdin_payload"] is not None for call in calls)
    assert all(len(call["stdin_payload"].decode()) <= COVER_PROMPT_MAX_CHARS for call in calls)
    assert all("--sandbox" in call["command"] for call in calls)
    assert all("workspace-write" in call["command"] for call in calls)
    assert all(call["command"] == (
        "codex", "exec", "--json", "--sandbox", "workspace-write",
        "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
        "--ephemeral", "--disable", "code_mode_host", "--disable", "code_mode",
        "--disable", "code_mode_only", "-c", 'approval_policy="never"', "-c",
        "mcp_servers={}", "-",
    ) for call in calls)
    copied_logins = [json.loads(call["auth"]) for call in calls]
    assert all(login == _REDACTED_CODEX_LOGIN for login in copied_logins)
    assert all("renewal-secret" not in call["auth"] for call in calls)
    for path in paths:
        with Image.open(audio_dir / path) as image:
            assert image.size == (1024, 1024)
            assert image.mode == "RGB"
            assert image.info == {}
    assert not list((audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).glob(".*.staging"))
    assert all(not Path(call["cwd"]).exists() for call in calls)


def test_cover_prompt_quotes_and_bounds_song_data(cover_job) -> None:
    factory, _, job_id = cover_job
    with factory() as session:
        job = session.get(Job, job_id)
        prompt = build_cover_prompt(job.album, job.album.songs)

    assert len(prompt) <= COVER_PROMPT_MAX_CHARS
    assert '"style_prompt":"' + "p" * COVER_PROMPT_SONG_FIELD_MAX_CHARS in prompt
    assert "p" * (COVER_PROMPT_SONG_FIELD_MAX_CHARS + 1) not in prompt
    assert '"lyrics_excerpt":"' + "l" * COVER_PROMPT_SONG_FIELD_MAX_CHARS in prompt
    assert "l" * (COVER_PROMPT_SONG_FIELD_MAX_CHARS + 1) not in prompt


@pytest.mark.parametrize(
    ("outcome", "expected_error"),
    [
        (
            _outcome(stdout='{"type":"item.completed","item":{"type":"command_execution"}}\n'),
            JOB_ERROR_COVER_IMAGE_TOOL_BLOCKED,
        ),
        (_outcome(stderr="401 unauthorized"), JOB_ERROR_COVER_CLI_LOGIN),
        (
            _outcome(stdout=(
                '{"type":"item.completed","item":{"type":"error",'
                '"message":"401 Unauthorized"}}\n'
            )),
            JOB_ERROR_COVER_CLI_LOGIN,
        ),
        (
            _outcome(stdout=(
                '{"type":"item.completed","item":{"type":"error",'
                '"message":"internal CLI failure"}}\n'
            )),
            JOB_ERROR_COVER_IMAGE_FAILED,
        ),
        (_outcome(stdout="not json\n"), JOB_ERROR_COVER_IMAGE_FAILED),
        (_outcome(stdout='{"type":"thread.started"}\n'), JOB_ERROR_COVER_IMAGE_FAILED),
    ],
)
def test_cover_job_leaves_no_group_for_named_image_failures(
    cover_job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    outcome: CliRunOutcome, expected_error: str,
) -> None:
    factory, audio_dir, job_id = cover_job
    _install_fake_codex_cli(monkeypatch, tmp_path, outcome=outcome)
    monkeypatch.setattr(
        "songmaker_cli.jobs.cover_suggestions.cover_image_provider_method",
        lambda: ProviderSetupMethod.CODEX_CLI,
    )

    asyncio.run(run_cover_suggestion_job(job_id, db_factory=factory, audio_dir=audio_dir))

    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.FAILED
        assert job.error == expected_error
        assert not job.album.cover_suggestions
    assert not (audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME / "album").exists()


def test_cover_job_reports_an_unavailable_cli_probe_as_an_image_failure(
    cover_job, monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, audio_dir, job_id = cover_job
    monkeypatch.setattr(
        "songmaker_cli.jobs.cover_suggestions.cover_image_provider_method",
        lambda: (_ for _ in ()).throw(ProviderUnavailableError(
            "codex",
            "cli",
            normalize_route_failure(SafeRouteReasonCode.CLI_BINARY_UNAVAILABLE),
        )),
    )

    asyncio.run(run_cover_suggestion_job(job_id, db_factory=factory, audio_dir=audio_dir))

    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.FAILED
        assert job.error == JOB_ERROR_COVER_IMAGE_FAILED


def test_cover_job_names_a_completed_turn_that_creates_no_image(
    cover_job, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, audio_dir, job_id = cover_job
    _install_fake_codex_cli(
        monkeypatch,
        tmp_path,
        outcome=_outcome(stdout=(_FIXTURES / "codex-cover-no-image-events.jsonl").read_text()),
        creates_artifact=False,
    )
    monkeypatch.setattr(
        "songmaker_cli.jobs.cover_suggestions.cover_image_provider_method",
        lambda: ProviderSetupMethod.CODEX_CLI,
    )

    asyncio.run(run_cover_suggestion_job(job_id, db_factory=factory, audio_dir=audio_dir))

    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.FAILED
        assert job.error == JOB_ERROR_COVER_IMAGE_NOT_CREATED
        assert not job.album.cover_suggestions


def test_codex_image_ignores_non_generated_png_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps(_REDACTED_CODEX_LOGIN))

    def fake_runner(_command, **kwargs):
        home = Path(kwargs["extra_env"]["CODEX_HOME"])
        artifact = home / "generated_images" / "cover.png"
        artifact.parent.mkdir()
        artifact.write_bytes(_png_bytes())
        bundled_asset = home / "skills" / "imagegen" / "assets" / "guide.png"
        bundled_asset.parent.mkdir(parents=True)
        bundled_asset.write_bytes(_png_bytes())
        return _outcome()

    monkeypatch.setattr(codex_cli_adapter, "CODEX_CLI_AUTH_FILE", str(auth_file))
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", fake_runner)

    assert codex_cli_adapter.generate_codex_cover_image("prompt", deadline=10_000_000).startswith(
        b"\x89PNG"
    )


def test_codex_image_rejects_an_artifact_outside_its_private_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps(_REDACTED_CODEX_LOGIN))
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png_bytes())
    homes: list[Path] = []

    def fake_runner(_command, **kwargs):
        homes.append(Path(kwargs["extra_env"]["CODEX_HOME"]))
        return _outcome()

    monkeypatch.setattr(codex_cli_adapter, "CODEX_CLI_AUTH_FILE", str(auth_file))
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", fake_runner)

    with pytest.raises(codex_cli_adapter.CodexImageNotCreatedError):
        codex_cli_adapter.generate_codex_cover_image("prompt", deadline=10_000_000)

    assert outside.exists()
    assert homes and all(not home.exists() for home in homes)


def test_codex_image_rejects_a_generated_images_symlink_outside_its_private_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps(_REDACTED_CODEX_LOGIN))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "cover.png").write_bytes(_png_bytes())
    homes: list[Path] = []

    def fake_runner(_command, **kwargs):
        home = Path(kwargs["extra_env"]["CODEX_HOME"])
        homes.append(home)
        (home / "generated_images").symlink_to(outside, target_is_directory=True)
        return _outcome()

    monkeypatch.setattr(codex_cli_adapter, "CODEX_CLI_AUTH_FILE", str(auth_file))
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", fake_runner)

    with pytest.raises(codex_cli_adapter.CodexImageArtifactError):
        codex_cli_adapter.generate_codex_cover_image("prompt", deadline=10_000_000)

    assert (outside / "cover.png").exists()
    assert homes and all(not home.exists() for home in homes)


def test_codex_image_timeout_cleans_its_private_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps(_REDACTED_CODEX_LOGIN))
    homes: list[Path] = []

    def fake_runner(_command, **kwargs):
        homes.append(Path(kwargs["extra_env"]["CODEX_HOME"]))
        return _outcome(
            complete=False,
            reason=CliRunReason.DEADLINE_WHILE_READING,
        )

    monkeypatch.setattr(codex_cli_adapter, "CODEX_CLI_AUTH_FILE", str(auth_file))
    monkeypatch.setattr(codex_cli_adapter, "run_cli_bounded", fake_runner)

    with pytest.raises(codex_cli_adapter.CodexImageTimeoutError):
        codex_cli_adapter.generate_codex_cover_image("prompt", deadline=10_000_000)

    assert homes and all(not home.exists() for home in homes)


@pytest.mark.parametrize(
    "document",
    (
        None,
        {**_REDACTED_CODEX_LOGIN, "tokens": {"id_token": "id-token"}},
    ),
)
def test_codex_image_names_missing_or_incomplete_login_mirrors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: dict | None,
) -> None:
    auth_file = tmp_path / "auth.json"
    if document is not None:
        auth_file.write_text(json.dumps(document))
    monkeypatch.setattr(codex_cli_adapter, "CODEX_CLI_AUTH_FILE", str(auth_file))

    with pytest.raises(codex_cli_adapter.CodexImageLoginError):
        codex_cli_adapter.generate_codex_cover_image("prompt", deadline=10_000_000)


def test_cancelled_cover_job_removes_its_staging_group(
    cover_job, monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, audio_dir, job_id = cover_job
    started = threading.Event()
    release = threading.Event()

    def delayed_image(_prompt: str, *, deadline: float) -> bytes:
        started.set()
        assert release.wait(timeout=1)
        return _png_bytes()

    monkeypatch.setattr(
        "songmaker_cli.jobs.cover_suggestions.cover_image_provider_method",
        lambda: ProviderSetupMethod.CODEX_CLI,
    )
    monkeypatch.setattr(
        "songmaker_cli.jobs.cover_suggestions.generate_codex_cover_image",
        delayed_image,
    )

    async def cancel_job() -> None:
        task = asyncio.create_task(
            run_cover_suggestion_job(job_id, db_factory=factory, audio_dir=audio_dir),
        )
        await asyncio.to_thread(started.wait)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(cancel_job())
    finally:
        release.set()

    with factory() as session:
        job = session.get(Job, job_id)
        assert job.status == JobStatus.FAILED
        assert not job.album.cover_suggestions
    assert not list((audio_dir / ALBUM_COVER_SUGGESTIONS_DIRNAME).glob(".*.staging"))
