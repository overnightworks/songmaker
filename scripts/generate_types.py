#!/usr/bin/env python3
"""Generate TypeScript API types from the FastAPI route contract."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "frontend" / "src" / "lib" / "api" / "types.ts"
CHECKED_MODE = "--check"
ROUTE_SOURCE = "FastAPI routes"
FALLBACK_SOURCE = "api_models exports"
INTERNAL_ROUTE_PREFIX = "/api/internal/"
INTERFACE_PATTERN = re.compile(r"^export interface (\w+)", re.MULTILINE)

HEADER = """\
/**
 * Auto-generated from the FastAPI API contract.
 * Do NOT edit manually — run: python scripts/generate_types.py
 *
 * Hierarchy: Song → Version (content) → Generation (MP3 output)
 */

export interface PaginatedResponse<T> {
\titems: T[];
\ttotal: number;
\toffset: number;
\tlimit: number;
\thas_more: boolean;
}"""

TS_MODEL_NAMES: dict[str, str] = {
    "AddAlbumToPlaylistResponse": "AddAlbumToPlaylistResult",
    "BaseGenerationParams": "VersionGenerationParams",
    "GenerationCreatedResourceEvent": "GenerationCreatedResourceEvent",
    "QueueStreamLibraryRequest": "LibraryQueueStreamRequest",
    "QueueStreamManifestResponse": "QueueStreamManifest",
    "QueueStreamSkipResponse": "QueueStreamSkipItem",
    "QueueStreamTrackResponse": "QueueStreamTrackItem",
    "ResourceHelloEvent": "ResourceHelloEvent",
    "ResourceResyncEvent": "ResourceResyncEvent",
    "AlbumResponse": "AlbumItem",
    "AuthMeResponse": "AuthUser",
    "AuditLogResponse": "AuditLogItem",
    "CapabilitiesResponse": "Capabilities",
    "ChatHistoryResponse": "ChatHistoryResult",
    "ChatMessageResponse": "ChatMessageItem",
    "ChatResponse": "ChatResult",
    "ChatTurnResponse": "ChatTurnResult",
    "ChatTurnV2Response": "ChatTurnV2Result",
    "CleanupResponse": "CleanupResult",
    "ConversationResponse": "ConversationItem",
    "CowriterSettingsResponse": "CowriterSettings",
    "GenerationParams": "VersionGenerationParams",
    "GenerationResponse": "GenerationItem",
    "JobResponse": "JobItem",
    "JudgeSettingsResponse": "JudgeSettings",
    "LastFailedGenerationResponse": "LastFailedGenerationResult",
    "LibraryPoolQueueResponse": "LibraryPoolQueue",
    "LibraryPoolTakeResponse": "LibraryPoolTakeItem",
    "LoadedModelDetail": "LoadedModelDetailItem",
    "LoginAttemptResponse": "LoginAttemptItem",
    "MemoryBundleResponse": "MemoryBundle",
    "MemoryScopeResponse": "MemoryScopeItem",
    "PlaylistAlbumSkipResponse": "PlaylistAlbumSkipItem",
    "PlaylistDetailResponse": "PlaylistDetailItem",
    "PlaylistEntryResponse": "PlaylistEntryItem",
    "PlaylistResponse": "PlaylistItem",
    "PresetResponse": "PresetItem",
    "ProviderStatusResponse": "ProviderStatus",
    "RateResponse": "RateResult",
    "RegistryModelResponse": "RegistryModelItem",
    "SessionResponse": "SessionItem",
    "SetupRequiredResponse": "SetupRequired",
    "SharedAlbumResponse": "SharedAlbumPayload",
    "SharedGenerationResponse": "SharedGenerationPayload",
    "SharedPlaylistEntryResponse": "SharedPlaylistEntryPayload",
    "SharedPlaylistResponse": "SharedPlaylistPayload",
    "SharedSongItem": "SharedAlbumSongPayload",
    "SharedSongResponse": "SharedSongPayload",
    "ShareResponse": "ShareResult",
    "SongResponse": "SongItem",
    "StoredGenerationParams": "GenerationParams",
    "UnplayableSongSummary": "UnplayableSongSummary",
    "UserLoraResponse": "UserLoraItem",
    "UserLoraSampleResponse": "UserLoraSampleItem",
    "UserResponse": "UserItem",
    "VersionResponse": "VersionItem",
    "WorkerEphemeralState": "WorkerEphemeralStateItem",
    "WorkerIdentity": "WorkerIdentityItem",
    "WorkerInfo": "WorkerInfoItem",
}

FIELD_TYPE_OVERRIDES: dict[tuple[str, str], str] = {
    ("GenerationItem", "scores"): "TrackScores | null",
    ("GenerationItem", "generation_params"): "GenerationParams | null",
    ("VersionItem", "generation_params"): "VersionGenerationParams | null",
    ("SongItem", "generation_params"): "VersionGenerationParams | null",
    ("SongItem", "best_scores"): "TrackScores | null",
    ("PresetItem", "params"): "VersionGenerationParams",
}
STRING_OUTPUT_KEYS = frozenset({"lyrical_summary", "detected_language"})


@dataclass(frozen=True)
class RouteExemption:
    prefix: str
    reason: str

    def applies_to(self, route: APIRoute) -> bool:
        return route.path.startswith(self.prefix)


EXEMPT_ROUTE_ROLES = (
    RouteExemption(
        prefix=INTERNAL_ROUTE_PREFIX,
        reason="worker registration is a backend-to-backend protocol, not a browser API",
    ),
)


@dataclass(frozen=True)
class ModelExemption:
    names: frozenset[str]
    reason: str

    def applies_to(self, model: type[BaseModel]) -> bool:
        return model.__name__ in self.names


EXEMPT_MODEL_ROLES = (
    ModelExemption(
        names=frozenset({"WorkerRegisterRequest", "WorkerRegisterResponse"}),
        reason="worker registration is a backend-to-backend protocol, not a browser API",
    ),
)


@dataclass(frozen=True)
class GenerationResult:
    content: str
    models: tuple[type[BaseModel], ...]
    route_models: int
    exported_models: int
    exempted_routes: int
    exempted_models: int


class TypeScriptTypeError(ValueError):
    pass


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _is_generic_model(model: type[BaseModel]) -> bool:
    metadata = getattr(model, "__pydantic_generic_metadata__", {})
    return metadata.get("origin") is not None or bool(metadata.get("parameters"))


def _models_in_annotation(annotation: Any) -> set[type[BaseModel]]:
    if _is_model(annotation):
        return {annotation}
    origin = get_origin(annotation)
    if origin is Annotated:
        return _models_in_annotation(get_args(annotation)[0])
    models: set[type[BaseModel]] = set()
    for argument in get_args(annotation):
        models.update(_models_in_annotation(argument))
    return models


def _route_annotations(routers: Iterable[APIRouter]) -> tuple[list[Any], int]:
    annotations: list[Any] = []
    exempted_routes = 0
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            if any(role.applies_to(route) for role in EXEMPT_ROUTE_ROLES):
                exempted_routes += 1
                continue
            if route.response_model is not None:
                annotations.append(route.response_model)
            annotations.extend(parameter.type_ for parameter in route.dependant.body_params)
    return annotations, exempted_routes


def _route_routers() -> tuple[APIRouter, ...]:
    from songmaker_cli.api import router as api_router
    from songmaker_cli.health_api import router as health_router
    from songmaker_cli.sharing_api import router as sharing_router

    return api_router, health_router, sharing_router


def _fallback_models() -> tuple[set[type[BaseModel]], int]:
    import songmaker_cli.api_models as api_models

    exported_models = {
        candidate
        for name in api_models.__all__
        if _is_model(candidate := getattr(api_models, name))
    }
    exempted_models = {
        model
        for model in exported_models
        if any(role.applies_to(model) for role in EXEMPT_MODEL_ROLES)
    }
    return exported_models - exempted_models, len(exempted_models)


def _closed_models(roots: Iterable[type[BaseModel]]) -> set[type[BaseModel]]:
    models = set(roots)
    pending = list(models)
    while pending:
        model = pending.pop()
        for field in model.model_fields.values():
            for nested in _models_in_annotation(field.annotation):
                if nested not in models:
                    models.add(nested)
                    pending.append(nested)
    return models


def _api_models(
    routers: Iterable[APIRouter] | None = None,
) -> tuple[set[type[BaseModel]], int, int, int, int]:
    if routers is not None:
        annotations, exempted_routes = _route_annotations(routers)
        roots = set().union(*(_models_in_annotation(annotation) for annotation in annotations))
        route_models = _closed_models(roots)
        return route_models, len(route_models), 0, exempted_routes, 0
    try:
        annotations, exempted_routes = _route_annotations(_route_routers())
    except Exception as error:
        print(f"WARNING: route introspection unavailable ({error}); using {FALLBACK_SOURCE}")
        fallback_models, exempted_models = _fallback_models()
        models = _closed_models(fallback_models)
        return models, 0, len(models), 0, exempted_models
    roots = set().union(*(_models_in_annotation(annotation) for annotation in annotations))
    route_models = _closed_models(roots)
    fallback_roots, exempted_models = _fallback_models()
    fallback_models = _closed_models(fallback_roots) - route_models
    return (
        route_models | fallback_models,
        len(route_models),
        len(fallback_models),
        exempted_routes,
        exempted_models,
    )


def _ts_name(model: type[BaseModel]) -> str:
    return TS_MODEL_NAMES.get(model.__name__, model.__name__)


def _py_type_to_ts(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _py_type_to_ts(get_args(annotation)[0])
    if origin is list:
        (inner,) = get_args(annotation)
        inner_type = _py_type_to_ts(inner)
        if get_origin(inner) in (UnionType, Union):
            inner_type = f"({inner_type})"
        return f"{inner_type}[]"
    if origin is dict:
        arguments = get_args(annotation)
        if not arguments:
            return "Record<string, unknown>"
        return f"Record<{_py_type_to_ts(arguments[0])}, {_py_type_to_ts(arguments[1])}>"
    if origin in (UnionType, Union):
        arguments = get_args(annotation)
        non_none = [argument for argument in arguments if argument is not type(None)]
        if len(arguments) == 2 and len(non_none) == 1:
            return f"{_py_type_to_ts(non_none[0])} | null"
        return " | ".join(_py_type_to_ts(argument) for argument in arguments)
    if origin is Literal:
        return " | ".join(
            repr(argument) if isinstance(argument, str) else str(argument)
            for argument in get_args(annotation)
        )
    type_map: dict[Any, str] = {
        str: "string",
        int: "number",
        float: "number",
        bool: "boolean",
        dict: "Record<string, unknown>",
        type(None): "null",
        object: "unknown",
    }
    if annotation in type_map:
        return type_map[annotation]
    if _is_model(annotation):
        return _ts_name(annotation)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return " | ".join(repr(member.value) for member in annotation)
    raise TypeScriptTypeError(f"unsupported Python annotation: {annotation!r}")


def _model_to_interface(model: type[BaseModel]) -> str:
    ts_name = _ts_name(model)
    lines = [f"export interface {ts_name} {{"]
    for field_name, field_info in model.model_fields.items():
        ts_type = FIELD_TYPE_OVERRIDES.get(
            (ts_name, field_name), _py_type_to_ts(field_info.annotation),
        )
        optional = "?" if not field_info.is_required() and field_info.default is None else ""
        lines.append(f"\t{field_name}{optional}: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


def _build_track_scores_interface() -> str:
    from songmaker_cli.scoring.registry import SCORERS

    fields = [
        (key, "string" if key in STRING_OUTPUT_KEYS else "number")
        for spec in SCORERS.values()
        for key in spec.output_keys
    ]
    fields.extend((("user_rating", "number"), ("user_notes", "string")))
    lines = ["export interface TrackScores {"]
    lines.extend(f"\t{name}?: {ts_type};" for name, ts_type in fields)
    lines.append("}")
    return "\n".join(lines)


def generate(routers: Iterable[APIRouter] | None = None) -> GenerationResult:
    (
        models,
        route_models,
        exported_models,
        exempted_routes,
        exempted_models,
    ) = _api_models(routers)
    from songmaker_cli.api_models import StoredGenerationParams

    models.add(StoredGenerationParams)
    emitted_models = sorted(
        (model for model in models if not _is_generic_model(model)),
        key=lambda model: (_ts_name(model), model.__module__, model.__name__),
    )
    blocks = [HEADER, _build_track_scores_interface()]
    blocks.extend(_model_to_interface(model) for model in emitted_models)
    return GenerationResult(
        content="\n\n".join(blocks) + "\n",
        models=tuple(emitted_models),
        route_models=route_models,
        exported_models=exported_models,
        exempted_routes=exempted_routes,
        exempted_models=exempted_models,
    )


def _checked_message(result: GenerationResult) -> str:
    return (
        f"Checked {len(result.models)} API models "
        f"({result.route_models} from {ROUTE_SOURCE}, "
        f"{result.exported_models} from {FALLBACK_SOURCE}; "
        f"{result.exempted_routes} exempt routes, {result.exempted_models} exempt models)"
    )


def check_generated_types(result: GenerationResult, output_path: Path = OUTPUT_PATH) -> bool:
    print(_checked_message(result))
    if not output_path.exists():
        print(f"FAIL: {output_path} does not exist")
        return False
    existing = output_path.read_text()
    if existing != result.content:
        existing_types = set(INTERFACE_PATTERN.findall(existing))
        missing_types = [
            _ts_name(model) for model in result.models if _ts_name(model) not in existing_types
        ]
        print(f"FAIL: {output_path} is out of sync with the FastAPI API models")
        if missing_types:
            print(f"FAIL: missing TypeScript types: {', '.join(missing_types)}")
        print("Run: python scripts/generate_types.py")
        return False
    print("OK: types.ts is in sync")
    return True


def main() -> None:
    result = generate()
    if CHECKED_MODE in sys.argv:
        sys.exit(0 if check_generated_types(result) else 1)
    OUTPUT_PATH.write_text(result.content)
    print(f"Generated {OUTPUT_PATH}")
    print(_checked_message(result))


if __name__ == "__main__":
    main()
