"""API key protection for every trading and control endpoint.

Fail closed: with no key configured the API answers 503 instead of running open. The only way to run
without a key is the explicit API_AUTH_DISABLED flag, which logs a warning.
"""

import logging
import secrets
from typing import Optional

from fastapi import Header, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)
_warned_disabled = False


def _warn_disabled_once() -> None:
    global _warned_disabled
    if not _warned_disabled:
        _warned_disabled = True
        logger.warning(
            "API authentication is DISABLED (API_AUTH_DISABLED=true): anyone who can reach this server can place orders"
        )


def _matches(candidate: Optional[str]) -> bool:
    expected = settings.CONTROL_API_KEY
    return bool(candidate) and bool(expected) and secrets.compare_digest(candidate.encode(), expected.encode())


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """FastAPI dependency: 503 when no key is configured, 401 when the header is missing or wrong."""
    if settings.API_AUTH_DISABLED:
        _warn_disabled_once()
        return
    if not settings.CONTROL_API_KEY:
        raise HTTPException(status_code=503, detail="API key not configured; set CONTROL_API_KEY")
    if not _matches(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def check_ws_token(token: Optional[str]) -> bool:
    """WebSocket variant: browsers cannot set headers, so the key arrives as ?token=."""
    if settings.API_AUTH_DISABLED:
        _warn_disabled_once()
        return True
    return _matches(token)
