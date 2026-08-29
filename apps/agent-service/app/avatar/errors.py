"""Provider errors mapped to stable HTTP/application errors."""


class ProviderError(RuntimeError):
    """Base error raised by a provider adapter."""


class ProviderNotConfiguredError(ProviderError):
    """Provider exists but credentials or runtime configuration are missing."""


class ProviderSessionError(ProviderError):
    """Provider cannot operate on the requested session."""
