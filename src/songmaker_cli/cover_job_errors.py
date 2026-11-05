"""Errors shared by cover-job execution entry points."""


class CoverSuggestionJobError(Exception):
    """The persisted cover job cannot safely produce a suggestion group."""
