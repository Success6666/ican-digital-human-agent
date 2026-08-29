"""Application-level errors with stable status mappings."""


class ApplicationError(RuntimeError):
    status_code = 400


class SessionNotFoundError(ApplicationError):
    status_code = 404


class SessionOwnershipError(ApplicationError):
    status_code = 403


class InvalidMessageError(ApplicationError):
    status_code = 422


class ProviderUnavailableError(ApplicationError):
    status_code = 503
