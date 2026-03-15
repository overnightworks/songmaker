"""ACE-Step music engine for Songmaker.

Generates complete songs via ACE-Step 1.5 (text-to-music AI).
REST API client talking to an ACE-Step server on localhost:8001.
"""

from acestep_engine.client import AceStepClient, is_acestep_available
from acestep_engine.errors import (
    AceStepError,
    AudioDownloadError,
    GenerationFailedError,
    GenerationTimeoutError,
    TaskSubmissionError,
)
from acestep_engine.models import AceStepConfig, AceStepResult

__all__ = [
    "AceStepClient",
    "AceStepConfig",
    "AceStepError",
    "AceStepResult",
    "AudioDownloadError",
    "GenerationFailedError",
    "GenerationTimeoutError",
    "TaskSubmissionError",
    "is_acestep_available",
]
