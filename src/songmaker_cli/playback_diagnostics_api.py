"""Playback diagnostics upload — transient evidence for #1187, logged and never stored.

Each recorded player event becomes one structured log line; no database row
and no Redis key are written, so deleting this module and the client recorder
removes the whole feature.
"""

from __future__ import annotations

from typing import Final

import structlog
from fastapi import APIRouter, Depends, Response, status
from webauth.dependencies import AuthenticatedUser

from songmaker_cli.api_models.playback_diagnostics import PlaybackDiagnosticsReport
from songmaker_cli.auth_dependencies import get_current_user

PLAYBACK_DIAGNOSTICS_LOGGER: Final = "songmaker.playback_diagnostics"
PLAYBACK_DIAGNOSTIC_LOG_EVENT: Final = "playback_diagnostic"

router = APIRouter()
log = structlog.stdlib.get_logger(PLAYBACK_DIAGNOSTICS_LOGGER)


@router.post("/playback-diagnostics", status_code=status.HTTP_204_NO_CONTENT)
def record_playback_diagnostics(
    report: PlaybackDiagnosticsReport,
    user: AuthenticatedUser = Depends(get_current_user),
) -> Response:
    report_fields = report.model_dump(mode="json", exclude={"events"})
    for event in report.events:
        log.info(
            PLAYBACK_DIAGNOSTIC_LOG_EVENT,
            user_id=user.id,
            **report_fields,
            **event.model_dump(mode="json"),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
