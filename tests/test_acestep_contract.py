"""Contract test: AceStepConfig must round-trip through the vendored ACE-Step model.

This is the lock that enforces Phase 3 of plans/acestep-naming-and-magic-strings.md.
If a future ACE-Step upgrade renames a field, this test fails on rebase rather
than at generation time.

The vendored model lives in vendor/acestep/ and is normally only importable
inside the ACE-Step venv. We inject the source dir into sys.path; the warning
about pydantic v1 config keys is benign — the vendored model uses
allow_population_by_field_name which pydantic v2 has renamed but still honours.
"""
from __future__ import annotations

import inspect
import re
import sys
import warnings
from dataclasses import asdict
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import mock_http_response as _mock_response

from acestep_engine.client import (
    _AUDIO_UPLOAD_FIELDS,
    AceStepClient,
    _build_submit_payload,
)

_VENDORED_ACESTEP_PATH = (
    Path(__file__).resolve().parent.parent / "vendor" / "acestep"
)
if str(_VENDORED_ACESTEP_PATH) not in sys.path:
    sys.path.insert(0, str(_VENDORED_ACESTEP_PATH))

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message=".*allow_population_by_field_name.*")
    try:
        from acestep.api.http.release_task_models import (  # type: ignore[import-not-found]
            GenerateMusicRequest,
        )
    except ImportError as exc:
        pytest.skip(
            f"vendored acestep package not importable: {exc}",
            allow_module_level=True,
        )

try:
    from acestep.api.http.release_task_request_parser import (  # type: ignore[import-not-found]
        parse_release_task_request,
    )
except ImportError:
    # Source: vendor/acestep/acestep/api/http/release_task_request_parser.py:110-111
    _FORK_MULTIPART_AUDIO_FIELDS = {
        "reference_audio_path": "ref_audio",
        "src_audio_path": "ctx_audio",
    }
else:
    parser_source = inspect.getsource(parse_release_task_request)

    def _primary_multipart_form_name(pattern: str) -> str:
        match = re.search(pattern, parser_source)
        assert match, f"Fork parser is missing primary multipart field: {pattern}"
        return match.group(1)

    _FORK_MULTIPART_AUDIO_FIELDS = {
        "reference_audio_path": _primary_multipart_form_name(
            r'ref_upload = form\.get\("([^\"]+)"\)',
        ),
        "src_audio_path": _primary_multipart_form_name(
            r'ctx_upload = form\.get\("([^\"]+)"\)',
        ),
    }

from acestep_engine.models import AceStepConfig  # noqa: E402


def _base_config(**overrides) -> AceStepConfig:
    defaults: dict[str, object] = {
        "prompt": "rock ballad with piano",
        "lyrics": "[verse]\nHello world\n[chorus]\nOh oh oh",
        "bpm": 120,
        "audio_duration": 60,
        "key_scale": "C major",
        "vocal_language": "en",
        "inference_steps": 8,
        "thinking": True,
    }
    defaults.update(overrides)
    return AceStepConfig(**defaults)


@pytest.mark.parametrize(
    ("task_type", "extras"),
    [
        ("text2music", {}),
        (
            "repaint",
            {
                "src_audio_path": "/tmp/src.wav",
                "repainting_start": 10.0,
                "repainting_end": 20.0,
                "repaint_mode": "balanced",
                "repaint_strength": 0.5,
            },
        ),
        (
            "cover",
            {
                "src_audio_path": "/tmp/src.wav",
                "audio_cover_strength": 0.8,
                "cover_noise_strength": 0.1,
            },
        ),
    ],
)
def test_acestep_config_validates_against_vendored_model(
    task_type: str, extras: dict[str, object],
) -> None:
    config = _base_config(task_type=task_type, **extras)
    payload = {k: v for k, v in asdict(config).items() if v not in (None, "", -1)}
    payload["use_random_seed"] = config.seed < 0
    payload["audio_format"] = "wav"

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*allow_population_by_field_name.*")
        model = GenerateMusicRequest(**payload)

    assert model.task_type == task_type
    assert model.prompt == config.prompt
    assert model.audio_duration == config.audio_duration
    assert model.key_scale == config.key_scale
    assert model.thinking is config.thinking
    if "src_audio_path" in extras:
        assert model.src_audio_path == extras["src_audio_path"]
    if "audio_cover_strength" in extras:
        assert model.audio_cover_strength == extras["audio_cover_strength"]


def test_acestep_config_has_no_unknown_fields() -> None:
    cfg_fields = {f.name for f in AceStepConfig.__dataclass_fields__.values()}
    model_fields = set(GenerateMusicRequest.model_fields.keys())
    songmaker_only = {"seed", "lora_path"}
    extra = cfg_fields - model_fields - songmaker_only
    assert not extra, (
        f"AceStepConfig fields missing from vendored GenerateMusicRequest: {extra}"
    )


def _multipart_form_parts(body: bytes, content_type: str) -> dict[str, bytes]:
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body,
    )
    return {
        part.get_param("name", header="content-disposition"): part.get_payload(
            decode=True,
        )
        for part in message.iter_parts()
    }


def test_submit_task_matches_fork_multipart_audio_contract(tmp_path) -> None:
    source_audio = tmp_path / "source.wav"
    reference_audio = tmp_path / "reference.wav"
    source_audio.write_bytes(b"source audio")
    reference_audio.write_bytes(b"reference audio")
    config = _base_config(
        task_type="repaint",
        src_audio_path=str(source_audio),
        reference_audio_path=str(reference_audio),
        repainting_start=10.0,
        repainting_end=20.0,
        repaint_mode="conservative",
        repaint_strength=0.25,
    )
    response_data = b'{"data":{"task_id":"multipart-1"},"code":200}'

    with patch("acestep_engine.client.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_response(response_data)
        assert AceStepClient()._submit_task(config) == "multipart-1"

    request = mock_urlopen.call_args.args[0]
    multipart_parts = _multipart_form_parts(
        request.data,
        request.headers["Content-type"],
    )
    audio_form_names = dict(_AUDIO_UPLOAD_FIELDS)

    assert audio_form_names == _FORK_MULTIPART_AUDIO_FIELDS
    assert multipart_parts[audio_form_names["src_audio_path"]] == b"source audio"
    assert multipart_parts[audio_form_names["reference_audio_path"]] == b"reference audio"

    multipart_values = {
        name: value.decode()
        for name, value in multipart_parts.items()
        if name not in audio_form_names.values()
    }
    assert set(multipart_values) <= set(GenerateMusicRequest.model_fields)
    assert "prompt" in multipart_values

    json_payload = _build_submit_payload(config)
    json_payload.pop("src_audio_path")
    json_payload.pop("reference_audio_path")
    assert multipart_values == {
        name: str(value).lower() if isinstance(value, bool) else str(value)
        for name, value in json_payload.items()
        if value is not None
    }
