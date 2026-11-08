"""API errors. One envelope everywhere, the same shape the Studio already uses: {"error": {"code", "message", "recommended_action"}}."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status = 400
    code = "bad_request"

    def __init__(
        self,
        message: str,
        *,
        recommended_action: str | None = None,
        details: dict[str, Any] | None = None,
        code: str | None = None,
    ):
        super().__init__(message)
        if code:
            self.code = code
        self.message = message
        self.recommended_action = recommended_action
        self.details = details or {}

    def body(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.recommended_action:
            err["recommended_action"] = self.recommended_action
        if self.details:
            err["details"] = self.details
        return {"error": err}


class Unauthorized(ApiError):
    status, code = 401, "unauthorized"


class NotFound(ApiError):
    status, code = 404, "not_found"


class Conflict(ApiError):
    status, code = 409, "conflict"


class InvalidRequest(ApiError):
    status, code = 422, "invalid_request"


class PaymentRequired(ApiError):
    status, code = 402, "insufficient_credits"


class TooManyRequests(ApiError):
    status, code = 429, "rate_limited"


class Unavailable(ApiError):
    status, code = 503, "unavailable"
