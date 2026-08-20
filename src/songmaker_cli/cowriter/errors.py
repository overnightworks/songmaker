"""Named co-writer provider failures. No silent fallback to another adapter."""


class ProviderUnavailableError(Exception):
    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(message)
