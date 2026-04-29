"""
ZerodhaAuth — token encryption and Redis storage for Kite Connect sessions.

This module is a refactored, self-contained replacement for the auth logic
previously scattered across app.auth.service. It is NOT imported by the
adapter directly; the adapter manages its own KiteConnect instance.
ZerodhaAuth is intended for use by the API layer that handles the OAuth
callback and persists tokens for headless session restoration.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ZerodhaAuth:
    """Encrypt/decrypt Zerodha tokens and persist them in Redis.

    Parameters
    ----------
    api_key : str
        Zerodha API key.
    api_secret : str
        Zerodha API secret.
    secret_key : str
        Application secret used to derive the Fernet encryption key.
    """

    def __init__(self, api_key: str, api_secret: str, secret_key: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._fernet_key = self._derive_fernet_key(secret_key)

    # ------------------------------------------------------------------
    # Key derivation
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_fernet_key(secret_key: str) -> bytes:
        """Derive a 32-byte URL-safe base64 key from an arbitrary string."""
        digest = hashlib.sha256(secret_key.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    def _encrypt_token(self, token: str) -> str:
        """Return Fernet-encrypted, UTF-8 encoded token."""
        from cryptography.fernet import Fernet  # noqa: PLC0415

        f = Fernet(self._fernet_key)
        return f.encrypt(token.encode()).decode()

    def _decrypt_token(self, encrypted: str) -> str:
        """Decrypt a previously encrypted token."""
        from cryptography.fernet import Fernet  # noqa: PLC0415

        f = Fernet(self._fernet_key)
        return f.decrypt(encrypted.encode()).decode()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def login(self, request_token: str) -> dict:
        """Exchange *request_token* for an access token and store it.

        Returns a dict with ``access_token``, ``user_id``, and ``is_valid``.
        """
        from kiteconnect import KiteConnect  # noqa: PLC0415

        kite = KiteConnect(api_key=self._api_key)
        data = kite.generate_session(request_token, api_secret=self._api_secret)
        access_token: str = data["access_token"]
        user_id: str = data.get("user_id", "")

        await self._store_tokens(
            access_token=access_token,
            public_token=data.get("public_token", ""),
            user_id=user_id,
        )

        return {
            "access_token": access_token,
            "user_id": user_id,
            "is_valid": True,
        }

    async def get_access_token(self) -> Optional[str]:
        """Retrieve and decrypt the stored access token. Returns None if absent."""
        try:
            from app.data.redis_client import get_redis  # noqa: PLC0415

            redis = get_redis()
            encrypted = await redis.get("zerodha:access_token")
            if not encrypted:
                return None
            return self._decrypt_token(
                encrypted if isinstance(encrypted, str) else encrypted.decode()
            )
        except Exception as exc:
            logger.warning("Failed to retrieve access token: %s", exc)
            return None

    async def logout(self) -> None:
        """Clear all stored Zerodha tokens from Redis."""
        try:
            from app.data.redis_client import get_redis  # noqa: PLC0415

            redis = get_redis()
            for key in (
                "zerodha:access_token",
                "zerodha:public_token",
                "zerodha:user_id",
                "zerodha:login_time",
            ):
                await redis.delete(key)
        except Exception as exc:
            logger.error("Logout failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _store_tokens(
        self, access_token: str, public_token: str, user_id: str
    ) -> None:
        from app.data.redis_client import get_redis  # noqa: PLC0415
        from datetime import datetime  # noqa: PLC0415

        redis = get_redis()
        ttl = 86400  # 24 h — tokens expire at Zerodha's end anyway
        await redis.setex(
            "zerodha:access_token", ttl, self._encrypt_token(access_token)
        )
        await redis.setex(
            "zerodha:public_token", ttl, self._encrypt_token(public_token)
        )
        await redis.setex("zerodha:user_id", ttl, user_id)
        await redis.set("zerodha:login_time", datetime.utcnow().isoformat())
