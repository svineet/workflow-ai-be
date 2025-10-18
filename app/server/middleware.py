from __future__ import annotations

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any
import jwt
from jwt import InvalidTokenError

from .settings import settings


def add_cors(app: FastAPI) -> None:
    origins = settings.CORS_ORIGINS or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _decode_supabase_jwt(token: str) -> Optional[Dict[str, Any]]:
    secret = settings.SUPABASE_JWT_SECRET
    if not secret:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except InvalidTokenError:
        return None


async def get_current_user_id(request: Request) -> Optional[str]:
    """Extract and verify Supabase JWT from Authorization header.

    Returns the user id (sub) on success, else None.
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    payload = _decode_supabase_jwt(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    sub = payload.get("sub") or payload.get("user_id")
    if not isinstance(sub, str) or not sub:
        raise HTTPException(status_code=401, detail="Invalid token subject")
    # Optionally attach to request.state
    try:
        request.state.user_id = sub
    except Exception:
        pass
    return sub


async def require_user_id(user_id: Optional[str] = Depends(get_current_user_id)) -> str:
    # In development or when SUPABASE_JWT_SECRET is unset, allow a system user fallback
    if not settings.SUPABASE_JWT_SECRET:
        return "system-user"
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id
