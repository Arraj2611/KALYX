"""GrowwAuth — TOTP-based authentication helper for the Groww Trading API."""

from __future__ import annotations


class GrowwAuth:
    """Generate a Groww access token using API key + TOTP secret.

    Parameters
    ----------
    api_key : str
        Groww API key.
    totp_secret : str
        Base-32 TOTP secret for the registered authenticator app.
    """

    def __init__(self, api_key: str, totp_secret: str) -> None:
        self._api_key = api_key
        self._totp_secret = totp_secret

    def get_access_token(self) -> str:
        """Derive a time-based OTP and exchange it for an access token.

        Imports growwapi and pyotp lazily so this module is importable
        even when those packages are absent (test environments).
        """
        import pyotp  # noqa: PLC0415
        from growwapi import GrowwAPI  # noqa: PLC0415

        totp = pyotp.TOTP(self._totp_secret)
        otp = totp.now()
        token = GrowwAPI.get_access_token(self._api_key, otp)
        return token
