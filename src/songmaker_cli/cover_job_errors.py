"""Errors shared by cover-job execution entry points."""


class CoverSuggestionJobError(Exception):
    """The persisted cover job cannot safely produce a suggestion group."""


class CoverImageToolUnavailableError(CoverSuggestionJobError):
    """The selected provider route cannot create cover images."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(provider)
