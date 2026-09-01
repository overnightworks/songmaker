"""Named co-writer provider failures. No silent fallback to another adapter."""


class ProviderError(Exception):
    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(message)


class ProviderUnavailableError(ProviderError):
    pass


class ProviderModelCatalogUnavailableError(ProviderError):
    pass
