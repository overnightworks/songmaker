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
from typing import Annotated, Any, Literal, Union, cast, get_args, get_origin

from fastapi import APIRouter
from fastapi.routing import APIRoute
from pydantic import BaseModel

try:
    from fastapi.routing import iter_route_contexts
except ImportError:  # FastAPI < 0.141 eagerly flattens included routers.
    iter_route_contexts = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "frontend" / "src" / "lib" / "api" / "types.ts"
CHECKED_MODE = "--check"
ROUTE_SOURCE = "FastAPI routes"
EXPORTED_SOURCE = "api_models exports"
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

    def applies_to(self, path: str) -> bool:
        return path.startswith(self.prefix)


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


@dataclass(frozen=True)
class DiscoveredModels:
    route_models: frozenset[type[BaseModel]]
    exported_models: frozenset[type[BaseModel]]
    exempted_routes: int
    exempted_models: int


@dataclass(frozen=True)
class DiscoveredRoute:
    path: str
    response_model: Any
    body_params: Iterable[Any]
    include_in_schema: bool


class TypeScriptTypeError(ValueError):
    pass


class RouteIntrospectionError(RuntimeError):
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


def _router_label(router: APIRouter) -> str:
    return getattr(router, "prefix", "") or "<root>"


def _discover_router_routes(
    router: APIRouter,
) -> tuple[DiscoveredRoute, ...]:
    """Return HTTP routes, including FastAPI's deferred router inclusions.

    FastAPI 0.141 represents ``include_router()`` with private
    ``_IncludedRouter`` instances until application startup. Earlier versions
    eagerly flatten those routes. The type contract needs the same endpoints
    in either representation.
    """
    if iter_route_contexts is not None:
        discovered = tuple(
            DiscoveredRoute(
                path=context.path,
                response_model=context.response_model,
                body_params=context.dependant.body_params,
                include_in_schema=context.include_in_schema,
            )
            for context in iter_route_contexts(router.routes)
            if isinstance(context.route, APIRoute)
        )
        if discovered:
            return discovered
        raise RouteIntrospectionError(
            f"router {_router_label(router)!r} has no HTTP API routes; "
            "its module may not have been imported or registered",
        )

    discovered = tuple(
        DiscoveredRoute(
            path=route.path,
            response_model=route.response_model,
            body_params=route.dependant.body_params,
            include_in_schema=route.include_in_schema,
        )
        for route in router.routes
        if isinstance(route, APIRoute)
    )

    if not discovered:
        raise RouteIntrospectionError(
            f"router {_router_label(router)!r} has no HTTP API routes; "
            "its module may not have been imported or registered",
        )
    return discovered


def _registered_child_routers(router: APIRouter) -> tuple[APIRouter, ...]:
    children: list[APIRouter] = []
    for route in router.routes:
        child_router = getattr(route, "original_router", None)
        if child_router is None:
            continue
        children.append(cast(APIRouter, child_router))
    return tuple(children)


def _complete_router_routes(
    router: APIRouter,
    *,
    ancestors: frozenset[int] = frozenset(),
) -> tuple[DiscoveredRoute, ...]:
    router_id = id(router)
    if router_id in ancestors:
        raise RouteIntrospectionError(
            f"router {_router_label(router)!r} includes itself recursively",
        )

    discovered = _discover_router_routes(router)
    child_routers = _registered_child_routers(router)
    if len(discovered) < len(child_routers):
        raise RouteIntrospectionError(
            f"router {_router_label(router)!r} exposes {len(discovered)} HTTP routes for "
            f"{len(child_routers)} registered router modules",
        )
    for child_router in child_routers:
        _complete_router_routes(child_router, ancestors=ancestors | {router_id})
    return discovered


def _body_parameter_annotation(parameter: Any) -> Any:
    annotation = getattr(parameter, "type_", None)
    if annotation is not None:
        return annotation

    annotation = getattr(getattr(parameter, "field_info", None), "annotation", None)
    if annotation is not None:
        return annotation
    raise RouteIntrospectionError("a route body parameter has no type annotation")


def _route_annotations(routers: Iterable[APIRouter]) -> tuple[list[Any], int]:
    annotations: list[Any] = []
    exempted_routes = 0
    for router in routers:
        for discovered_route in _complete_router_routes(router):
            if any(role.applies_to(discovered_route.path) for role in EXEMPT_ROUTE_ROLES):
                exempted_routes += 1
                continue
            if discovered_route.response_model is not None:
                annotations.append(discovered_route.response_model)
            annotations.extend(
                _body_parameter_annotation(parameter) for parameter in discovered_route.body_params
            )
    return annotations, exempted_routes


def _route_routers() -> tuple[APIRouter, ...]:
    from songmaker_cli.api import router as api_router
    from songmaker_cli.health_api import router as health_router
    from songmaker_cli.sharing_api import router as sharing_router

    return api_router, health_router, sharing_router


def _exported_models() -> tuple[set[type[BaseModel]], int]:
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
    *,
    include_exported_models: bool = False,
) -> DiscoveredModels:
    if routers is None:
        routers = _route_routers()
        include_exported_models = True
    annotations, exempted_routes = _route_annotations(routers)
    roots = set().union(*(_models_in_annotation(annotation) for annotation in annotations))
    route_models = _closed_models(roots)
    if not include_exported_models:
        return DiscoveredModels(frozenset(route_models), frozenset(), exempted_routes, 0)
    exported_roots, exempted_models = _exported_models()
    exported_models = _closed_models(exported_roots) - route_models
    return DiscoveredModels(
        route_models=frozenset(route_models),
        exported_models=frozenset(exported_models),
        exempted_routes=exempted_routes,
        exempted_models=exempted_models,
    )


def _ts_name(model: type[BaseModel]) -> str:
    return TS_MODEL_NAMES.get(model.__name__, model.__name__)


def _py_type_to_ts(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin is Annotated:
        return _py_type_to_ts(get_args(annotation)[0])
    if origin is list:
        (inner,) = get_args(annotation)
        while get_origin(inner) is Annotated:
            inner = get_args(inner)[0]
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


def generate(
    routers: Iterable[APIRouter] | None = None,
    *,
    include_exported_models: bool = False,
) -> GenerationResult:
    discovered_models = _api_models(routers, include_exported_models=include_exported_models)
    route_models = tuple(
        model for model in discovered_models.route_models if not _is_generic_model(model)
    )
    exported_models = tuple(
        model for model in discovered_models.exported_models if not _is_generic_model(model)
    )
    emitted_models = sorted(
        (*route_models, *exported_models),
        key=lambda model: (_ts_name(model), model.__module__, model.__name__),
    )
    blocks = [HEADER, _build_track_scores_interface()]
    blocks.extend(_model_to_interface(model) for model in emitted_models)
    return GenerationResult(
        content="\n\n".join(blocks) + "\n",
        models=tuple(emitted_models),
        route_models=len(route_models),
        exported_models=len(exported_models),
        exempted_routes=discovered_models.exempted_routes,
        exempted_models=discovered_models.exempted_models,
    )


def _checked_message(result: GenerationResult) -> str:
    return (
        f"Checked {len(result.models)} API models "
        f"({result.route_models} from {ROUTE_SOURCE}, "
        f"{result.exported_models} from {EXPORTED_SOURCE}; "
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
    try:
        routers = _route_routers()
    except ImportError as error:
        print(f"FAIL: route introspection unavailable: {error}")
        sys.exit(1)
    try:
        result = generate(routers, include_exported_models=True)
    except RouteIntrospectionError as error:
        print(f"FAIL: route introspection incomplete: {error}")
        sys.exit(1)
    if CHECKED_MODE in sys.argv:
        sys.exit(0 if check_generated_types(result) else 1)
    OUTPUT_PATH.write_text(result.content)
    print(f"Generated {OUTPUT_PATH}")
    print(_checked_message(result))


if __name__ == "__main__":
    main()
