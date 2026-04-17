from __future__ import annotations


class ServiceError(Exception):
    default_status_code = 500

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        self.detail = detail
        self.status_code = self.default_status_code if status_code is None else status_code
        super().__init__(detail)


class BadRequestError(ServiceError):
    default_status_code = 400


class UnauthorizedError(ServiceError):
    default_status_code = 401


class NotFoundError(ServiceError):
    default_status_code = 404


class ServiceUnavailableError(ServiceError):
    default_status_code = 503


class InternalServiceError(ServiceError):
    default_status_code = 500
