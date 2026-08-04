"""Consistent error rendering.

Every failure leaves the API in the :class:`~reim.schemas.common.ErrorResponse`
shape, so a client only ever parses one error format.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from reim.core.exceptions import REIMError
from reim.core.logging import get_logger

logger = get_logger(__name__)


def _envelope(
    code: str, message: str, details: dict[str, object] | None = None
) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach the handlers that produce the uniform error envelope."""

    @app.exception_handler(REIMError)
    async def _handle_domain_error(_request: Request, exc: REIMError) -> JSONResponse:
        if exc.http_status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            logger.error("api.domain_error", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.http_status,
            content=_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(part) for part in error["loc"][1:]) or "<body>",
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,  # Unprocessable Content
            content=_envelope(
                "validation_error",
                "One or more request parameters are invalid",
                {"fields": fields},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        codes = {
            status.HTTP_404_NOT_FOUND: "not_found",
            status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
        }
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(codes.get(exc.status_code, "http_error"), str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals to the client; the detail goes to the logs only.
        logger.exception("api.unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred"),
        )
