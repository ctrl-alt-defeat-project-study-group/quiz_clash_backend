"""
Origin-based CSRF protection middleware for cookie-authenticated state-changing requests.
"""
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _extract_origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


class CSRFOriginMiddleware(BaseHTTPMiddleware):
    """
    Validate Origin (or Referer fallback) against settings.FRONTEND_ORIGINS
    for state-changing requests (POST, PUT, PATCH, DELETE).
    """

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            allowed = {o.rstrip("/") for o in settings.FRONTEND_ORIGINS}
            # Allow same-origin requests (e.g. Swagger UI /docs calling the API on its own host)
            self_origin = _extract_origin(str(request.url))
            if self_origin:
                allowed.add(self_origin)

            if origin is not None:
                if origin.rstrip("/") not in allowed:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": {
                                "code": "FORBIDDEN",
                                "message": "CSRF check failed: untrusted Origin header.",
                            }
                        },
                    )
            elif referer is not None:
                referer_origin = _extract_origin(referer)
                if referer_origin not in allowed:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": {
                                "code": "FORBIDDEN",
                                "message": "CSRF check failed: untrusted Referer header.",
                            }
                        },
                    )

        return await call_next(request)
