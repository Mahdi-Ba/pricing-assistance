"""Application errors and their RFC 9457 problem-details representation.

Every error response has ``type``, ``title``, ``status``, ``detail``, ``correlation_id`` and a
Persian ``message_fa`` for the workspace. Internal details never leak into responses.
"""

from typing import Any, ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from pricing_assistant.core.correlation import get_correlation_id
from pricing_assistant.core.logging import get_logger

PROBLEM_MEDIA_TYPE = "application/problem+json"
_TYPE_PREFIX = "urn:tunoo:pricing:problem:"
_SERVER_ERROR = 500

log = get_logger(__name__)


class Problem(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str
    correlation_id: str
    message_fa: str


class AppError(Exception):
    """Base class for errors that map to a problem-details response."""

    status: ClassVar[int] = 500
    code: ClassVar[str] = "internal_error"
    title: ClassVar[str] = "Internal error"
    default_message_fa: ClassVar[str] = "خطای داخلی رخ داد. لطفاً دوباره تلاش کنید."

    def __init__(
        self,
        detail: str | None = None,
        *,
        message_fa: str | None = None,
        code: str | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.message_fa = message_fa or self.default_message_fa
        self.problem_code = code or self.code
        self.extra = extra or {}
        self.headers = headers or {}


class AuthenticationRequired(AppError):
    status = 401
    code = "authentication_required"
    title = "Authentication required"
    default_message_fa = "برای ادامه وارد شوید."


class PermissionDenied(AppError):
    status = 403
    code = "permission_denied"
    title = "Permission denied"
    default_message_fa = "شما اجازه انجام این کار را ندارید."


class NotFound(AppError):
    status = 404
    code = "not_found"
    title = "Not found"
    default_message_fa = "مورد درخواستی یافت نشد."


class Conflict(AppError):
    status = 409
    code = "conflict"
    title = "Conflict"
    default_message_fa = "وضعیت این مورد تغییر کرده است."


class ValidationFailed(AppError):
    status = 422
    code = "validation_failed"
    title = "Validation failed"
    default_message_fa = "اطلاعات واردشده معتبر نیست."


class PayloadTooLarge(AppError):
    status = 413
    code = "payload_too_large"
    title = "Payload too large"
    default_message_fa = "حجم فایل بیش از حد مجاز است."


class UnsupportedMediaType(AppError):
    status = 415
    code = "unsupported_media_type"
    title = "Unsupported media type"
    default_message_fa = "نوع فایل پشتیبانی نمی‌شود."


class TooManyRequests(AppError):
    status = 429
    code = "too_many_requests"
    title = "Too many requests"
    default_message_fa = "سقف درخواست پر شده است."


class ServiceUnavailable(AppError):
    status = 503
    code = "service_unavailable"
    title = "Service unavailable"
    default_message_fa = "این سرویس در حال حاضر در دسترس نیست. بعداً دوباره تلاش کنید."


def problem_response(
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    message_fa: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = Problem(
        type=_TYPE_PREFIX + code,
        title=title,
        status=status,
        detail=detail,
        correlation_id=get_correlation_id(),
        message_fa=message_fa,
        **(extra or {}),
    )
    return JSONResponse(
        body.model_dump(mode="json"),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


async def _app_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - registered for AppError only
    if exc.status >= _SERVER_ERROR:
        log.error("request.failed", code=exc.problem_code, detail=exc.detail)
    return problem_response(
        status=exc.status,
        code=exc.problem_code,
        title=exc.title,
        detail=exc.detail,
        message_fa=exc.message_fa,
        extra=exc.extra,
        headers=exc.headers,
    )


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    errors = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    return problem_response(
        status=422,
        code=ValidationFailed.code,
        title=ValidationFailed.title,
        detail="Request validation failed",
        message_fa=ValidationFailed.default_message_fa,
        extra={"errors": errors},
    )


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    return problem_response(
        status=exc.status_code,
        code=f"http_{exc.status_code}",
        title=str(exc.detail),
        detail=str(exc.detail),
        message_fa=(
            AppError.default_message_fa
            if exc.status_code >= _SERVER_ERROR
            else "درخواست نامعتبر است."
        ),
        headers=dict(exc.headers or {}),
    )


async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    log.exception("request.unhandled_error", error_type=type(exc).__name__)
    return problem_response(
        status=500,
        code=AppError.code,
        title=AppError.title,
        detail="An unexpected error occurred",
        message_fa=AppError.default_message_fa,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
