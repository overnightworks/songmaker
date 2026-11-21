"""ACE-Step engine exceptions."""

from __future__ import annotations


class AceStepError(Exception):
    """Base exception for ACE-Step engine errors."""


class TaskSubmissionError(AceStepError):
    """Failed to submit generation task."""


class GenerationFailedError(AceStepError):
    """ACE-Step generation failed on the server side."""


class GpuOutOfMemoryError(GenerationFailedError):
    """ACE-Step generation failed because GPU memory was insufficient."""


class GenerationTimeoutError(AceStepError):
    """ACE-Step generation timed out."""


class AudioDownloadError(AceStepError):
    """Failed to download generated audio."""
