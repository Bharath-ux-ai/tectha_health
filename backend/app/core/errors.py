class ServiceError(Exception):
    """Business-rule violation surfaced to the client with a clear message."""

    def __init__(self, message: str, status_code: int = 400, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class NotFound(ServiceError):
    def __init__(self, message: str = "Not found."):
        super().__init__(message, 404, "not_found")


class Conflict(ServiceError):
    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message, 409, code)
