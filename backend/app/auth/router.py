"""
Zerodha authentication API router.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from app.auth.service import AuthService

router = APIRouter()


class TokenRequest(BaseModel):
    """Request token model."""
    request_token: str


class TokenResponse(BaseModel):
    """Token response model."""
    access_token: Optional[str] = None
    public_token: Optional[str] = None
    user_id: Optional[str] = None
    is_valid: bool


@router.post("/login", response_model=TokenResponse)
async def login(request: TokenRequest):
    """Login with Zerodha request token."""
    try:
        auth_service = AuthService()
        result = await auth_service.login(request.request_token)
        return TokenResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/status", response_model=TokenResponse)
async def get_auth_status():
    """Get current authentication status."""
    try:
        auth_service = AuthService()
        status = await auth_service.get_status()
        return TokenResponse(**status)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh")
async def refresh_token():
    """Refresh access token."""
    try:
        auth_service = AuthService()
        result = await auth_service.refresh_token()
        return {"success": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/logout")
async def logout():
    """Logout and clear tokens."""
    try:
        auth_service = AuthService()
        await auth_service.logout()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

