"""
Structured API error helpers and global FastAPI exception handlers.
"""
import logging
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def api_error(status_code: int, code: str, message: str) -> HTTPException:
    """Build a structured HTTPException matching the API contract."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Convert FastAPI/Pydantic validation errors to the contract error format."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        msg = err.get("msg", "Invalid value")
        parts.append(f"{loc}: {msg}" if loc else msg)
    message = "; ".join(parts) if parts else "Request validation failed."
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": "VALIDATION_ERROR", "message": message}},
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch unhandled server exceptions and return a structured 500 response."""
    logger.exception("Unhandled server exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": {
                "code": "SERVER_ERROR",
                "message": "An unexpected server error occurred.",
            }
        },
    )
