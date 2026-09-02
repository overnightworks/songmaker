"""What the agent-CLI login mirror publishes, and what it refuses to publish."""

from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import mirror_agent_cli_credentials as mirror  # noqa: E402

CLAUDE = {
    "claudeAiOauth": {
        "accessToken": "access-token",
        "refreshToken": "the-long-lived-secret",
        "expiresAt": 1,
        "refreshTokenExpiresAt": 2,
        "scopes": ["user:inference"],
        "subscriptionType": "max",
        "rateLimitTier": "default",
    },
}
# The measured field set, not a stand-in: the mirror now insists on every
# field its CLI needs, so a shortened fixture would test a document grok
# itself would reject.
GROK = {
    "https://auth.x.ai::realm": {
        "key": "access-jwt",
        "refresh_token": "the-long-lived-secret",
        "auth_mode": "oidc",
        "create_time": "2026-09-01T21:13:08.000Z",
        "expires_at": "2026-09-02T03:13:08.000Z",
        "user_id": "user-1",
        "team_id": "team-1",
        "principal_type": "User",
        "principal_id": "user-1",
        "oidc_issuer": "https://auth.x.ai",
        "oidc_client_id": "client-1",
        "coding_data_retention_opt_out": True,
        "email": "someone@example.com",
        "first_name": "Some",
        "last_name": "One",
        "profile_image_asset_id": "users/1234",
    },
}
CODEX = {
    "auth_mode": "chatgpt",
    "tokens": {
        "id_token": "id-jwt",
        "access_token": "access-jwt",
        "refresh_token": "the-long-lived-secret",
        "account_id": "acct",
    },
    "last_refresh": "2026-08-31T22:44:00Z",
}


@pytest.fixture
def home(tmp_path: Path) -> Path:
    signed_in = tmp_path / "home"
    for relative, document in (
        (".claude/.credentials.json", CLAUDE),
        (".grok/auth.json", GROK),
        (".codex/auth.json", CODEX),
    ):
        path = signed_in / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document))
    return signed_in


@pytest.fixture
def mirror_dir(tmp_path: Path) -> Path:
    return tmp_path / "mirror"


def _published(mirror_dir: Path, name: str) -> dict:
    return json.loads((mirror_dir / name).read_text())


# ── what leaves the host ───────────────────────────────────────────


def test_no_renewal_secret_reaches_the_mirror(home: Path, mirror_dir: Path) -> None:
    assert mirror.mirror(home, mirror_dir) == 0

    published = "\n".join(
        (mirror_dir / name).read_text() for name in ("claude.json", "grok.json", "codex.json")
    )
    assert "the-long-lived-secret" not in published


def test_claude_keeps_only_the_fields_its_cli_needs(home: Path, mirror_dir: Path) -> None:
    mirror.mirror(home, mirror_dir)

    assert _published(mirror_dir, "claude.json") == {
        "claudeAiOauth": {
            "accessToken": "access-token",
            "expiresAt": 1,
            "scopes": ["user:inference"],
        },
    }


def test_grok_keeps_its_shape_but_drops_the_operators_person(
    home: Path, mirror_dir: Path,
) -> None:
    """Grok's CLI needs every field but these four, and blanks refresh fine."""
    mirror.mirror(home, mirror_dir)
    (entry,) = _published(mirror_dir, "grok.json").values()

    assert entry["refresh_token"] == ""
    assert entry["create_time"] == GROK["https://auth.x.ai::realm"]["create_time"]
    assert not {"email", "first_name", "last_name", "profile_image_asset_id"} & set(entry)


def test_codex_keeps_the_refresh_field_but_empties_it(home: Path, mirror_dir: Path) -> None:
    """Its CLI refuses a document without the field, and accepts an empty one."""
    mirror.mirror(home, mirror_dir)
    tokens = _published(mirror_dir, "codex.json")["tokens"]

    assert tokens["refresh_token"] == ""
    assert tokens["id_token"] == "id-jwt"
    assert tokens["access_token"] == "access-jwt"


def test_a_cli_that_is_not_signed_in_is_published_as_signed_out(
    home: Path, mirror_dir: Path,
) -> None:
    (home / ".grok/auth.json").unlink()

    assert mirror.mirror(home, mirror_dir) == 0
    assert _published(mirror_dir, "grok.json") == {}


def test_an_unreadable_source_leaves_the_last_good_copy_alone(
    home: Path, mirror_dir: Path,
) -> None:
    mirror.mirror(home, mirror_dir)
    good = (mirror_dir / "claude.json").read_text()
    (home / ".claude/.credentials.json").write_text("{not json")

    assert mirror.mirror(home, mirror_dir) == 1
    assert (mirror_dir / "claude.json").read_text() == good


# ── how it writes ──────────────────────────────────────────────────


def test_the_mirror_file_keeps_its_inode_so_the_mount_keeps_working(
    home: Path, mirror_dir: Path,
) -> None:
    mirror.mirror(home, mirror_dir)
    before = (mirror_dir / "claude.json").stat().st_ino

    mirror.mirror(home, mirror_dir)

    assert (mirror_dir / "claude.json").stat().st_ino == before


def test_shorter_content_is_padded_rather_than_truncated(mirror_dir: Path) -> None:
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "claude.json"
    mirror.write_in_place(target, b'{"a": "aaaaaaaaaaaaaaaaaaaaaaaa"}')
    long_size = target.stat().st_size

    mirror.write_in_place(target, b'{"b": 1}')

    assert target.stat().st_size == long_size
    assert json.loads(target.read_text()) == {"b": 1}


def test_a_write_that_does_not_land_completely_is_reported(
    monkeypatch: pytest.MonkeyPatch, mirror_dir: Path,
) -> None:
    """A short write is the one moment a reader could see a mixed document."""
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "claude.json"

    real_pwrite = os.pwrite

    def _writes_almost_nothing(descriptor, payload, offset):
        return real_pwrite(descriptor, payload[:1], offset) if offset == 0 else 0

    monkeypatch.setattr(mirror.os, "pwrite", _writes_almost_nothing)
    with pytest.raises(mirror.MirrorError, match="accepted no bytes"):
        mirror.write_in_place(target, b'{"a": 1}')


# ── what it refuses to touch ───────────────────────────────────────


def test_a_symlinked_target_is_never_followed(home: Path, mirror_dir: Path, tmp_path) -> None:
    mirror.prepare_mirror_directory(mirror_dir)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("untouched")
    (mirror_dir / "claude.json").symlink_to(elsewhere)

    assert mirror.mirror(home, mirror_dir) == 1
    assert elsewhere.read_text() == "untouched"


def test_a_target_with_a_second_hard_link_is_refused(
    home: Path, mirror_dir: Path, tmp_path,
) -> None:
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "claude.json"
    target.touch()
    os.link(target, tmp_path / "alias")

    assert mirror.mirror(home, mirror_dir) == 1


def test_a_mirror_directory_others_can_read_is_refused(mirror_dir: Path) -> None:
    mirror_dir.mkdir()
    mirror_dir.chmod(0o755)

    with pytest.raises(mirror.MirrorError, match="0755"):
        mirror.prepare_mirror_directory(mirror_dir)


def test_a_new_mirror_directory_is_private_from_the_start(mirror_dir: Path) -> None:
    mirror.prepare_mirror_directory(mirror_dir)

    assert mirror_dir.stat().st_mode & 0o777 == 0o700


def test_a_source_larger_than_a_login_document_is_refused(
    monkeypatch, home: Path, mirror_dir: Path,
) -> None:
    """Valid JSON in the first bytes, more after them: judged in full or not at all.

    Reading only the first N bytes and mirroring what parses would publish a
    document whose remainder nobody ever looked at.
    """
    mirror.mirror(home, mirror_dir)
    good = (mirror_dir / "claude.json").read_text()
    # Above the other two fixtures, below this one once padded, so exactly one
    # source is over the limit.
    monkeypatch.setattr(mirror, "SOURCE_READ_LIMIT_BYTES", 1500)
    (home / ".claude/.credentials.json").write_text(json.dumps(CLAUDE) + " " * 1500)

    assert mirror.mirror(home, mirror_dir) == 1
    assert (mirror_dir / "claude.json").read_text() == good


# ── a field we have never measured is not published ────────────────


@pytest.mark.parametrize(
    ("relative", "document", "where"),
    [
        (
            ".grok/auth.json",
            {"realm": {**GROK["https://auth.x.ai::realm"], "device_refresh_token": "s"}},
            "grok",
        ),
        (
            ".codex/auth.json",
            {**CODEX, "device_code": "s"},
            "codex",
        ),
        (
            ".codex/auth.json",
            {**CODEX, "tokens": {**CODEX["tokens"], "session_refresh_token": "s"}},
            "codex",
        ),
    ],
)
def test_a_field_the_mirror_has_never_seen_stops_it(
    home: Path, mirror_dir: Path, relative, document, where,
) -> None:
    """Grok and Codex carry their whole document, so an unknown field is a risk.

    Their CLIs need every field, which is exactly why a new one cannot be
    waved through: `device_refresh_token` would ride into the container
    unnoticed. The operator sees a named error instead.
    """
    mirror.mirror(home, mirror_dir)
    good = (mirror_dir / f"{where}.json").read_text()
    (home / relative).write_text(json.dumps(document))

    assert mirror.mirror(home, mirror_dir) == 1
    assert (mirror_dir / f"{where}.json").read_text() == good


def test_an_openai_key_in_the_codex_login_is_not_handed_on(
    home: Path, mirror_dir: Path,
) -> None:
    (home / ".codex/auth.json").write_text(
        json.dumps({**CODEX, "OPENAI_API_KEY": "sk-the-operators-key"}),
    )

    assert mirror.mirror(home, mirror_dir) == 0
    published = _published(mirror_dir, "codex.json")
    assert published["OPENAI_API_KEY"] is None
    assert "sk-the-operators-key" not in (mirror_dir / "codex.json").read_text()


def test_a_new_claude_field_is_simply_not_carried(home: Path, mirror_dir: Path) -> None:
    """Claude takes an allowlist, so an added field needs no decision at all."""
    (home / ".claude/.credentials.json").write_text(
        json.dumps(
            {"claudeAiOauth": {**CLAUDE["claudeAiOauth"], "deviceToken": "s"}},
        ),
    )

    assert mirror.mirror(home, mirror_dir) == 0
    assert "deviceToken" not in _published(mirror_dir, "claude.json")["claudeAiOauth"]


# ── verifying what is about to be mounted ──────────────────────────


def test_verify_passes_what_the_mirror_itself_wrote(home: Path, mirror_dir: Path) -> None:
    mirror.mirror(home, mirror_dir)

    assert mirror.verify(mirror_dir) == 0


def test_verify_refuses_a_hand_copied_login(home: Path, mirror_dir: Path) -> None:
    mirror.mirror(home, mirror_dir)
    (mirror_dir / "claude.json").write_text(json.dumps(CLAUDE))

    assert mirror.verify(mirror_dir) == 1


def test_verify_refuses_a_symlinked_mirror_file(
    home: Path, mirror_dir: Path, tmp_path,
) -> None:
    mirror.mirror(home, mirror_dir)
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text("{}")
    (mirror_dir / "grok.json").unlink()
    (mirror_dir / "grok.json").symlink_to(elsewhere)

    assert mirror.verify(mirror_dir) == 1


def test_verify_names_a_missing_mirror_rather_than_crashing(mirror_dir: Path) -> None:
    mirror.prepare_mirror_directory(mirror_dir)

    assert mirror.verify(mirror_dir) == 3


def test_a_timestamp_called_last_refresh_is_not_mistaken_for_a_token(
    home: Path, mirror_dir: Path,
) -> None:
    """Crying wolf on `last_refresh` is how a check gets switched off."""
    mirror.mirror(home, mirror_dir)

    assert "last_refresh" in _published(mirror_dir, "codex.json")
    assert mirror.verify(mirror_dir) == 0


# ── where the mirror lives ─────────────────────────────────────────


def test_an_exported_directory_wins_over_the_env_file(
    monkeypatch, tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("SONGMAKER_CLI_CREDENTIALS_DIR=/from/file\n")
    monkeypatch.setenv("SONGMAKER_CLI_CREDENTIALS_DIR", "/from/environment")

    resolved = mirror.resolve_mirror_directory(tmp_path, Path("/home/someone"))

    assert resolved == Path("/from/environment")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("SONGMAKER_CLI_CREDENTIALS_DIR=/srv/creds", "/srv/creds"),
        ('SONGMAKER_CLI_CREDENTIALS_DIR="/srv/creds"', "/srv/creds"),
        ("SONGMAKER_CLI_CREDENTIALS_DIR='/srv/creds'", "/srv/creds"),
        ('SONGMAKER_CLI_CREDENTIALS_DIR="/srv/creds" # note', "/srv/creds"),
        ("SONGMAKER_CLI_CREDENTIALS_DIR=/srv/creds # note", "/srv/creds"),
        ("SONGMAKER_CLI_CREDENTIALS_DIR=~/creds", "/home/someone/creds"),
        ("  SONGMAKER_CLI_CREDENTIALS_DIR = /srv/creds  ", "/srv/creds"),
        # Compose accepts a colon as the separator, and an export prefix.
        ("SONGMAKER_CLI_CREDENTIALS_DIR: /srv/creds", "/srv/creds"),
        ("export SONGMAKER_CLI_CREDENTIALS_DIR=/srv/creds", "/srv/creds"),
        # A '#' only starts a comment when whitespace precedes it, so this is
        # a path with a '#' in it — Compose keeps it, and so do we.
        ("SONGMAKER_CLI_CREDENTIALS_DIR=/srv/creds#blue", "/srv/creds#blue"),
        # The last assignment wins, as in Compose.
        (
            "SONGMAKER_CLI_CREDENTIALS_DIR=/srv/first\n"
            "SONGMAKER_CLI_CREDENTIALS_DIR=/srv/last",
            "/srv/last",
        ),
    ],
)
def test_the_env_file_is_read_the_way_compose_reads_it(
    monkeypatch, tmp_path: Path, line, expected,
) -> None:
    monkeypatch.delenv("SONGMAKER_CLI_CREDENTIALS_DIR", raising=False)
    (tmp_path / ".env").write_text(line + "\n")

    resolved = mirror.resolve_mirror_directory(tmp_path, Path("/home/someone"))

    assert resolved == Path(expected)


@pytest.mark.parametrize(
    "line",
    [
        'SONGMAKER_CLI_CREDENTIALS_DIR="/srv/songmaker credentials" # note',
        "SONGMAKER_CLI_CREDENTIALS_DIR=/srv/%h/creds",
        "SONGMAKER_CLI_CREDENTIALS_DIR=relative/creds",
        'SONGMAKER_CLI_CREDENTIALS_DIR="/srv/unclosed',
        # Outside the subset this reader implements. Guessing differently from
        # Compose would point the mirror somewhere else, so it refuses.
        r'SONGMAKER_CLI_CREDENTIALS_DIR="/srv/a\tb"',
        "SONGMAKER_CLI_CREDENTIALS_DIR=/srv/$HOME/creds",
        'SONGMAKER_CLI_CREDENTIALS_DIR="/srv/creds" trailing',
    ],
)
def test_a_directory_no_unit_could_carry_is_refused(
    monkeypatch, tmp_path: Path, line,
) -> None:
    """systemd splits on whitespace and expands %, so such a path is refused."""
    monkeypatch.delenv("SONGMAKER_CLI_CREDENTIALS_DIR", raising=False)
    (tmp_path / ".env").write_text(line + "\n")

    with pytest.raises(mirror.MirrorError):
        mirror.resolve_mirror_directory(tmp_path, Path("/home/someone"))


def test_an_exported_but_empty_variable_means_the_default(
    monkeypatch, tmp_path: Path,
) -> None:
    """Compose's `${VAR:-default}` treats empty as unset, so this does too."""
    (tmp_path / ".env").write_text("SONGMAKER_CLI_CREDENTIALS_DIR=/from/file\n")
    monkeypatch.setenv("SONGMAKER_CLI_CREDENTIALS_DIR", "")

    resolved = mirror.resolve_mirror_directory(tmp_path, Path("/home/someone"))

    assert resolved == Path("/home/someone/.songmaker/agent-cli-credentials")


def test_without_configuration_the_mirror_lives_under_the_owners_home(
    monkeypatch, tmp_path: Path,
) -> None:
    monkeypatch.delenv("SONGMAKER_CLI_CREDENTIALS_DIR", raising=False)

    resolved = mirror.resolve_mirror_directory(tmp_path, Path("/home/someone"))

    assert resolved == Path("/home/someone/.songmaker/agent-cli-credentials")


# ── one run at a time ──────────────────────────────────────────────


def test_a_run_that_never_gets_the_lock_fails_instead_of_claiming_success(
    monkeypatch, mirror_dir: Path,
) -> None:
    """Standing down on any lock trouble let the stack start on stale files."""
    mirror.prepare_mirror_directory(mirror_dir)
    monkeypatch.setattr(mirror, "LOCK_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(mirror, "LOCK_POLL_SECONDS", 0.01)

    def _always_contended(_descriptor, _operation):
        raise OSError(errno.EAGAIN, "would block")

    monkeypatch.setattr(mirror.fcntl, "flock", _always_contended)
    with pytest.raises(mirror.MirrorError, match="held the lock"):
        mirror._take_lock(0)


def test_a_lock_error_that_is_not_contention_is_a_failure(
    monkeypatch, mirror_dir: Path,
) -> None:
    def _broken(_descriptor, _operation):
        raise OSError(errno.EIO, "disk fell over")

    monkeypatch.setattr(mirror.fcntl, "flock", _broken)
    with pytest.raises(mirror.MirrorError, match="could not lock"):
        mirror._take_lock(0)


# ── a field its CLI needs is not optional ──────────────────────────


def _required_field_cases() -> list[tuple[str, str, str]]:
    """Every field each provider declares as required, not a sample of them.

    Sampling left `key`, `auth_mode`, `id_token` and `access_token` removable
    from the required sets without a single red test.
    """
    cases = [(".claude/.credentials.json", f, "claude") for f in sorted(
        mirror.CLAUDE_REQUIRED_FIELDS,
    )]
    cases += [(".grok/auth.json", f, "grok") for f in sorted(
        mirror.GROK_REQUIRED_FIELDS,
    )]
    cases += [(".codex/auth.json", f, "codex") for f in sorted(
        mirror.CODEX_REQUIRED_FIELDS - {"tokens"},
    )]
    cases += [(".codex/auth.json", f, "codex") for f in sorted(
        mirror.CODEX_TOKEN_REQUIRED_FIELDS,
    )]
    return cases


@pytest.mark.parametrize(
    ("relative", "removed", "published"), _required_field_cases(),
)
def test_a_document_its_cli_could_not_use_is_not_published(
    home: Path, mirror_dir: Path, relative, removed, published,
) -> None:
    """Replacing a good copy with an unusable one is a silent sign-out."""
    mirror.mirror(home, mirror_dir)
    good = (mirror_dir / f"{published}.json").read_text()
    document = json.loads((home / relative).read_text())
    _drop_field(document, removed)
    (home / relative).write_text(json.dumps(document))

    assert mirror.mirror(home, mirror_dir) == 1
    assert (mirror_dir / f"{published}.json").read_text() == good


def _drop_field(document: dict, field: str) -> None:
    for container in (document, *(v for v in document.values() if isinstance(v, dict))):
        if field in container:
            del container[field]
            return
        nested = container.get("tokens")
        if isinstance(nested, dict) and field in nested:
            del nested[field]
            return
    raise AssertionError(f"{field} was not in the document to begin with")


def test_the_fields_the_mirror_keeps_are_the_ones_it_publishes(
    home: Path, mirror_dir: Path,
) -> None:
    mirror.mirror(home, mirror_dir)

    assert set(_published(mirror_dir, "claude.json")["claudeAiOauth"]) == {
        "accessToken", "expiresAt", "scopes",
    }
    (grok_entry,) = _published(mirror_dir, "grok.json").values()
    assert set(grok_entry) == (
        mirror.GROK_ALLOWED_FIELDS | mirror.GROK_BLANKED_FIELDS
    )
    codex = _published(mirror_dir, "codex.json")
    assert set(codex["tokens"]) == (
        mirror.CODEX_TOKEN_ALLOWED_FIELDS | mirror.CODEX_TOKEN_BLANKED_FIELDS
    )


# ── the verifier ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cli", "document"),
    [
        ("claude", {"claudeAiOauth": {"refreshToken": "s"}}),
        ("grok", {"realm": {"refresh_token": "s"}}),
        ("codex", {"tokens": {"device_refresh_token": "s"}}),
        ("claude", {"claudeAiOauth": {"refreshToken": ["s"]}}),
        ("grok", {"realm": {"refresh_token": {"value": "s"}}}),
    ],
)
def test_the_verifier_refuses_a_renewal_token_of_any_shape(
    mirror_dir: Path, cli, document,
) -> None:
    """A list or an object under a refresh key is a token just the same."""
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / f"{cli}.json"
    mirror.write_in_place(target, json.dumps(document).encode())

    with pytest.raises(mirror.MirrorError, match="renewal token"):
        mirror.verify_mirror_file(target, cli)


def test_the_verifier_accepts_an_emptied_renewal_field(mirror_dir: Path) -> None:
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "grok.json"
    mirror.write_in_place(target, json.dumps({"r": {"refresh_token": ""}}).encode())

    mirror.verify_mirror_file(target, "grok")


def test_the_verifier_refuses_a_file_others_can_read(mirror_dir: Path) -> None:
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "claude.json"
    mirror.write_in_place(target, b"{}")
    target.chmod(0o644)

    with pytest.raises(mirror.MirrorError, match="0644"):
        mirror.verify_mirror_file(target, "claude")


def test_the_verifier_refuses_a_second_hard_link(mirror_dir: Path, tmp_path) -> None:
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "claude.json"
    mirror.write_in_place(target, b"{}")
    os.link(target, tmp_path / "alias")

    with pytest.raises(mirror.MirrorError, match="hard link"):
        mirror.verify_mirror_file(target, "claude")


def test_the_verifier_refuses_a_file_another_account_owns(
    monkeypatch, mirror_dir: Path,
) -> None:
    """Ownership is checked on the open descriptor, and it has to be checked."""
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "claude.json"
    mirror.write_in_place(target, b"{}")
    somebody_else = os.getuid() + 1
    monkeypatch.setattr(mirror.os, "getuid", lambda: somebody_else)

    with pytest.raises(mirror.MirrorError, match="owned by uid"):
        mirror.verify_mirror_file(target, "claude")


def test_the_verifier_refuses_a_file_too_large_to_judge_in_full(
    monkeypatch, mirror_dir: Path,
) -> None:
    """Valid JSON first, anything at all after the read limit — never looked at."""
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "claude.json"
    mirror.write_in_place(target, b'{"a": 1}' + b" " * 200)
    # Patched only now, so write_in_place could still create the file: what is
    # under test is the judging, not the writing.
    monkeypatch.setattr(mirror, "SOURCE_READ_LIMIT_BYTES", 64)

    with pytest.raises(mirror.MirrorError, match="cannot be judged in full"):
        mirror.verify_mirror_file(target, "claude")


def test_the_verifier_refuses_something_that_is_not_json(mirror_dir: Path) -> None:
    mirror.prepare_mirror_directory(mirror_dir)
    target = mirror_dir / "claude.json"
    mirror.write_in_place(target, b"not json at all")

    with pytest.raises(mirror.MirrorError, match="not a JSON"):
        mirror.verify_mirror_file(target, "claude")
