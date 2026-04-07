#!/usr/bin/env python3
"""Generate TypeScript interfaces from Pydantic response models.

Reads api_models.py and scoring/models.py, produces frontend/src/lib/api/types.ts.
Run after changing any API response model to keep the contract in sync.

Usage:
    python scripts/generate_types.py          # write types.ts
    python scripts/generate_types.py --check  # exit 1 if types.ts would change
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "frontend" / "src" / "lib" / "api" / "types.ts"

HEADER = """\
/**
 * Auto-generated from api_models.py and scoring/models.py.
 * Do NOT edit manually — run: python scripts/generate_types.py
 *
 * Hierarchy: Song → Version (content) → Generation (MP3 output)
 */

export interface PaginatedResponse<T> {
\titems: T[];
\ttotal: number;
\toffset: number;
\tlimit: number;
}"""

_RESPONSE_MODEL_NAMES: dict[str, str] = {
    "AlbumResponse": "AlbumItem",
    "GenerationResponse": "GenerationItem",
    "VersionResponse": "VersionItem",
    "SongResponse": "SongItem",
    "JobResponse": "JobItem",
    "CapabilitiesResponse": "Capabilities",
    "AuthMeResponse": "AuthUser",
    "SetupRequiredResponse": "SetupRequired",
    "UserResponse": "UserItem",
    "SessionResponse": "SessionItem",
    "PresetResponse": "PresetItem",
    "LoginAttemptResponse": "LoginAttemptItem",
    "AuditLogResponse": "AuditLogItem",
    "RateLimitItem": "RateLimitItem",
    "RateLimitsResponse": "RateLimitsResponse",
    "UserRateLimitsResponse": "UserRateLimitsResponse",
    "GenerationParams": "VersionGenerationParams",
    "StoredGenerationParams": "GenerationParams",
    "ChatResponse": "ChatResult",
    "ChatMessageResponse": "ChatMessageItem",
    "ChatTurnResponse": "ChatTurnResult",
    "ChatHistoryResponse": "ChatHistoryResult",
    "RecentChatItem": "RecentChatItem",
    "RateResponse": "RateResult",
    "CleanupResponse": "CleanupResult",
    "ShareResponse": "ShareResult",
    "PlaylistResponse": "PlaylistItem",
    "PlaylistEntryResponse": "PlaylistEntryItem",
    "PlaylistDetailResponse": "PlaylistDetailItem",
    "WorkerIdentity": "WorkerIdentityItem",
    "WorkerEphemeralState": "WorkerEphemeralStateItem",
    "WorkerInfo": "WorkerInfoItem",
    "WorkerPoolResponse": "WorkerPoolResponse",
    "RegistryModelResponse": "RegistryModelItem",
    "RegistryResponse": "RegistryResponse",
}

_FIELD_TYPE_OVERRIDES: dict[tuple[str, str], str] = {
    ("GenerationItem", "scores"): "TrackScores | null",
    ("GenerationItem", "generation_params"): "GenerationParams | null",
    ("VersionItem", "generation_params"): "VersionGenerationParams | null",
    ("SongItem", "generation_params"): "VersionGenerationParams | null",
    ("SongItem", "best_scores"): "TrackScores | null",
    ("PresetItem", "params"): "VersionGenerationParams",
}

_EMIT_ORDER: list[str] = [
    "GenerationParams",
    "VersionGenerationParams",
    "TrackScores",
    "GenerationItem",
    "VersionItem",
    "SongItem",
    "AlbumItem",
    "JobItem",
    "Capabilities",
    "AuthUser",
    "SetupRequired",
    "UserItem",
    "SessionItem",
    "PresetItem",
    "LoginAttemptItem",
    "AuditLogItem",
    "RateLimitItem",
    "RateLimitsResponse",
    "UserRateLimitsResponse",
    "ChatResult",
    "ChatMessageItem",
    "ChatTurnResult",
    "ChatHistoryResult",
    "RecentChatItem",
    "RateResult",
    "CleanupResult",
    "ShareResult",
    "PlaylistEntryItem",
    "PlaylistItem",
    "PlaylistDetailItem",
    "WorkerIdentityItem",
    "WorkerEphemeralStateItem",
    "WorkerInfoItem",
    "WorkerPoolResponse",
    "RegistryModelItem",
    "RegistryResponse",
]


def _py_type_to_ts(annotation: Any, field_info: FieldInfo | None = None) -> str:
    """Convert a Python type annotation to a TypeScript type string."""
    origin = get_origin(annotation)

    if origin is list:
        (inner,) = get_args(annotation)
        return f"{_py_type_to_ts(inner)}[]"

    if origin is dict:
        args = get_args(annotation)
        if args:
            key_type = _py_type_to_ts(args[0])
            val_type = _py_type_to_ts(args[1])
            return f"Record<{key_type}, {val_type}>"
        return "Record<string, unknown>"

    if origin is type(int | str):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(args) == 2:
            return f"{_py_type_to_ts(non_none[0])} | null"
        return " | ".join(_py_type_to_ts(a) for a in args)

    try:
        import typing
        if origin is typing.Union:
            args = get_args(annotation)
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1 and len(args) == 2:
                return f"{_py_type_to_ts(non_none[0])} | null"
            return " | ".join(_py_type_to_ts(a) for a in args)
    except AttributeError:
        pass

    try:
        import typing
        if origin is typing.Literal:
            args = get_args(annotation)
            return " | ".join(f"'{a}'" if isinstance(a, str) else str(a) for a in args)
    except AttributeError:
        pass

    type_map: dict[type | str, str] = {
        str: "string",
        int: "number",
        float: "number",
        bool: "boolean",
        type(None): "null",
    }

    if annotation in type_map:
        return type_map[annotation]

    if isinstance(annotation, str):
        return annotation

    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _RESPONSE_MODEL_NAMES.get(annotation.__name__, annotation.__name__)

    if hasattr(annotation, "__name__"):
        return type_map.get(annotation.__name__, "unknown")

    return "unknown"


def _model_to_interface(model: type[BaseModel], ts_name: str) -> str:
    """Convert a Pydantic model to a TypeScript interface declaration."""
    lines = [f"export interface {ts_name} {{"]

    for field_name, field_info in model.model_fields.items():
        override_key = (ts_name, field_name)
        if override_key in _FIELD_TYPE_OVERRIDES:
            ts_type = _FIELD_TYPE_OVERRIDES[override_key]
        else:
            ts_type = _py_type_to_ts(field_info.annotation, field_info)

        has_none_default = (
            not field_info.is_required()
            and field_info.default is None
        )
        optional_marker = "?" if has_none_default else ""

        lines.append(f"\t{field_name}{optional_marker}: {ts_type};")

    lines.append("}")
    return "\n".join(lines)


def _build_generation_params_interface() -> str:
    """Build GenerationParams from the StoredGenerationParams Pydantic model."""
    from songmaker_cli.api_models import StoredGenerationParams

    return _model_to_interface(StoredGenerationParams, "GenerationParams")


def _build_track_scores_interface() -> str:
    """Build TrackScores from scoring/models.py SCORE_KEY_* constants."""
    from songmaker_cli.scoring.models import (
        SCORE_KEY_AUDIOBOX_COMPLEXITY,
        SCORE_KEY_AUDIOBOX_ENJOYMENT,
        SCORE_KEY_AUDIOBOX_QUALITY,
        SCORE_KEY_AUDIOBOX_UNDERSTANDING,
        SCORE_KEY_BPM_DETECTED,
        SCORE_KEY_BPM_DEVIATION,
        SCORE_KEY_DYNAMICS,
        SCORE_KEY_DYNAMICS_ONSET_CV,
        SCORE_KEY_DYNAMICS_PITCH_CV,
        SCORE_KEY_DYNAMICS_RMS_CONTRAST,
        SCORE_KEY_LYRICAL_COHERENCE,
        SCORE_KEY_LYRICAL_SUMMARY,
        SCORE_KEY_SILENCE_GAPS,
        SCORE_KEY_SILENCE_LONGEST,
        SCORE_KEY_SPECTRAL_ARTIFACTS,
        SCORE_KEY_TEXT_ACCURACY,
    )

    fields: list[tuple[str, str]] = [
        (SCORE_KEY_LYRICAL_COHERENCE, "number"),
        (SCORE_KEY_LYRICAL_SUMMARY, "string"),
        (SCORE_KEY_DYNAMICS, "number"),
        (SCORE_KEY_DYNAMICS_PITCH_CV, "number"),
        (SCORE_KEY_DYNAMICS_RMS_CONTRAST, "number"),
        (SCORE_KEY_DYNAMICS_ONSET_CV, "number"),
        (SCORE_KEY_TEXT_ACCURACY, "number"),
        (SCORE_KEY_AUDIOBOX_ENJOYMENT, "number"),
        (SCORE_KEY_AUDIOBOX_UNDERSTANDING, "number"),
        (SCORE_KEY_AUDIOBOX_COMPLEXITY, "number"),
        (SCORE_KEY_AUDIOBOX_QUALITY, "number"),
        (SCORE_KEY_BPM_DETECTED, "number"),
        (SCORE_KEY_BPM_DEVIATION, "number"),
        (SCORE_KEY_SILENCE_GAPS, "number"),
        (SCORE_KEY_SILENCE_LONGEST, "number"),
        (SCORE_KEY_SPECTRAL_ARTIFACTS, "number"),
        ("user_rating", "number"),
        ("user_notes", "string"),
    ]

    lines = ["export interface TrackScores {"]
    for name, ts_type in fields:
        lines.append(f"\t{name}?: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


def generate() -> str:
    from songmaker_cli.api_models import (
        AlbumResponse,
        AuditLogResponse,
        AuthMeResponse,
        CapabilitiesResponse,
        ChatHistoryResponse,
        ChatMessageResponse,
        ChatResponse,
        ChatTurnResponse,
        CleanupResponse,
        GenerationParams,
        GenerationResponse,
        JobResponse,
        LoginAttemptResponse,
        PlaylistDetailResponse,
        PlaylistEntryResponse,
        PlaylistResponse,
        PresetResponse,
        RateLimitItem,
        RateLimitsResponse,
        RateResponse,
        RecentChatItem,
        RegistryModelResponse,
        RegistryResponse,
        SessionResponse,
        SetupRequiredResponse,
        ShareResponse,
        SongResponse,
        UserRateLimitsResponse,
        UserResponse,
        VersionResponse,
        WorkerEphemeralState,
        WorkerIdentity,
        WorkerInfo,
        WorkerPoolResponse,
    )

    models: dict[str, type[BaseModel]] = {
        "VersionGenerationParams": GenerationParams,
        "GenerationItem": GenerationResponse,
        "VersionItem": VersionResponse,
        "SongItem": SongResponse,
        "AlbumItem": AlbumResponse,
        "JobItem": JobResponse,
        "Capabilities": CapabilitiesResponse,
        "AuthUser": AuthMeResponse,
        "SetupRequired": SetupRequiredResponse,
        "UserItem": UserResponse,
        "SessionItem": SessionResponse,
        "PresetItem": PresetResponse,
        "LoginAttemptItem": LoginAttemptResponse,
        "AuditLogItem": AuditLogResponse,
        "RateLimitItem": RateLimitItem,
        "RateLimitsResponse": RateLimitsResponse,
        "UserRateLimitsResponse": UserRateLimitsResponse,
        "ChatResult": ChatResponse,
        "ChatMessageItem": ChatMessageResponse,
        "ChatTurnResult": ChatTurnResponse,
        "ChatHistoryResult": ChatHistoryResponse,
        "RecentChatItem": RecentChatItem,
        "RateResult": RateResponse,
        "CleanupResult": CleanupResponse,
        "ShareResult": ShareResponse,
        "PlaylistEntryItem": PlaylistEntryResponse,
        "PlaylistItem": PlaylistResponse,
        "PlaylistDetailItem": PlaylistDetailResponse,
        "WorkerIdentityItem": WorkerIdentity,
        "WorkerEphemeralStateItem": WorkerEphemeralState,
        "WorkerInfoItem": WorkerInfo,
        "WorkerPoolResponse": WorkerPoolResponse,
        "RegistryModelItem": RegistryModelResponse,
        "RegistryResponse": RegistryResponse,
    }

    blocks: list[str] = [HEADER]

    for ts_name in _EMIT_ORDER:
        if ts_name == "GenerationParams":
            blocks.append(_build_generation_params_interface())
            continue
        if ts_name == "TrackScores":
            blocks.append(_build_track_scores_interface())
            continue
        model = models.get(ts_name)
        if model is None:
            continue
        blocks.append(_model_to_interface(model, ts_name))

    return "\n\n".join(blocks) + "\n"


def main() -> None:
    check_mode = "--check" in sys.argv

    content = generate()

    if check_mode:
        if not OUTPUT_PATH.exists():
            print(f"FAIL: {OUTPUT_PATH} does not exist")
            sys.exit(1)
        existing = OUTPUT_PATH.read_text()
        if existing != content:
            print(f"FAIL: {OUTPUT_PATH} is out of sync with api_models.py")
            print("Run: python scripts/generate_types.py")
            sys.exit(1)
        print("OK: types.ts is in sync")
        sys.exit(0)

    OUTPUT_PATH.write_text(content)
    print(f"Generated {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
