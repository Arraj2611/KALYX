"""
Zerodha authentication service.
Handles token management, refresh, and session validation.
"""
import logging
from typing import Optional, Dict
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
from cryptography.fernet import Fernet
import base64
import hashlib

from app.config import settings
from app.data.redis_client import get_redis

logger = logging.getLogger(__name__)


class AuthService:
    """Service for managing Zerodha authentication."""
    
    def __init__(self):
        self.api_key = settings.ZERODHA_API_KEY
        self.api_secret = settings.ZERODHA_API_SECRET
        self.kite: Optional[KiteConnect] = None
        self._encryption_key = self._get_encryption_key()
    
    def _get_encryption_key(self) -> bytes:
        """Get or generate encryption key for token storage."""
        if settings.ENCRYPTION_KEY:
            # Use provided key (base64 encoded)
            return base64.urlsafe_b64decode(settings.ENCRYPTION_KEY.encode())
        else:
            # Generate key from secret key
            key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
            return base64.urlsafe_b64encode(key)[:32]
    
    def _encrypt_token(self, token: str) -> str:
        """Encrypt token for storage."""
        f = Fernet(self._encryption_key)
        return f.encrypt(token.encode()).decode()
    
    def _decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt stored token."""
        f = Fernet(self._encryption_key)
        return f.decrypt(encrypted_token.encode()).decode()
    
    async def login(self, request_token: str) -> Dict:
        """Login with request token and store access token."""
        try:
            # Generate session
            kite = KiteConnect(api_key=self.api_key)
            data = kite.generate_session(request_token, api_secret=self.api_secret)
            
            access_token = data["access_token"]
            public_token = data.get("public_token", "")
            user_id = data.get("user_id", "")
            
            # Store tokens in Redis (encrypted)
            redis = get_redis()
            await redis.setex(
                "zerodha:access_token",
                86400,  # 24 hours
                self._encrypt_token(access_token)
            )
            await redis.setex(
                "zerodha:public_token",
                86400,
                self._encrypt_token(public_token)
            )
            await redis.setex(
                "zerodha:user_id",
                86400,
                user_id
            )
            await redis.set("zerodha:login_time", datetime.utcnow().isoformat())
            
            # Initialize Kite client
            self.kite = KiteConnect(api_key=self.api_key)
            self.kite.set_access_token(access_token)
            
            logger.info(f"Successfully logged in. User ID: {user_id}")
            
            return {
                "access_token": access_token[:10] + "..." if access_token else None,
                "public_token": public_token[:10] + "..." if public_token else None,
                "user_id": user_id,
                "is_valid": True
            }
        except Exception as e:
            logger.error(f"Login failed: {e}", exc_info=True)
            raise
    
    async def get_status(self) -> Dict:
        """Get current authentication status."""
        try:
            redis = get_redis()
            access_token_enc = await redis.get("zerodha:access_token")
            
            if not access_token_enc:
                return {
                    "access_token": None,
                    "public_token": None,
                    "user_id": None,
                    "is_valid": False
                }
            
            # Decrypt and validate token
            access_token = self._decrypt_token(access_token_enc)
            kite = KiteConnect(api_key=self.api_key)
            kite.set_access_token(access_token)
            
            # Validate by fetching profile
            profile = kite.profile()
            user_id = profile.get("user_id", "")
            
            return {
                "access_token": access_token[:10] + "...",
                "public_token": (await redis.get("zerodha:public_token") or "")[:10] + "...",
                "user_id": user_id,
                "is_valid": True
            }
        except Exception as e:
            logger.warning(f"Token validation failed: {e}")
            return {
                "access_token": None,
                "public_token": None,
                "user_id": None,
                "is_valid": False
            }
    
    async def refresh_token(self) -> bool:
        """Refresh access token (if supported by Zerodha)."""
        # Note: Zerodha tokens typically last 24 hours and require new request_token
        # This method can be used to re-validate existing token
        try:
            status = await self.get_status()
            if status["is_valid"]:
                return True
            else:
                logger.warning("Cannot refresh token. New request_token required.")
                return False
        except Exception as e:
            logger.error(f"Token refresh failed: {e}", exc_info=True)
            raise
    
    async def logout(self):
        """Logout and clear stored tokens."""
        try:
            redis = get_redis()
            await redis.delete("zerodha:access_token")
            await redis.delete("zerodha:public_token")
            await redis.delete("zerodha:user_id")
            await redis.delete("zerodha:login_time")
            self.kite = None
            logger.info("Logged out successfully")
        except Exception as e:
            logger.error(f"Logout failed: {e}", exc_info=True)
            raise
    
    def get_kite_client(self) -> Optional[KiteConnect]:
        """Get initialized Kite client instance."""
        if self.kite:
            return self.kite
        
        # Try to initialize from stored token
        try:
            redis = get_redis()
            access_token_enc = redis.get("zerodha:access_token")
            if access_token_enc:
                access_token = self._decrypt_token(access_token_enc)
                self.kite = KiteConnect(api_key=self.api_key)
                self.kite.set_access_token(access_token)
                return self.kite
        except Exception as e:
            logger.error(f"Failed to initialize Kite client: {e}", exc_info=True)
        
        return None

