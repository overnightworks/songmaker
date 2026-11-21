"""ACE-Step music engine for Songmaker.

Generates complete songs via ACE-Step 1.5 (text-to-music AI).
REST API client talking to an ACE-Step server at the host and port its caller passes.
"""

from songmaker_acestep_engine.client import AceStepClient
from songmaker_acestep_engine.errors import (
    AceStepError,
    AudioDownloadError,
    GenerationFailedError,
    GenerationTimeoutError,
    TaskSubmissionError,
)
from songmaker_acestep_engine.models import AceStepConfig, AceStepResult

__all__ = [
    "AceStepClient",
    "AceStepConfig",
    "AceStepError",
    "AceStepResult",
    "AudioDownloadError",
    "GenerationFailedError",
    "GenerationTimeoutError",
    "TaskSubmissionError",
]
