from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import httpx
import jwt
from jwt import PyJWKClient
from typing import Optional, Dict, Any

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


class _SupabaseAuthMiddleware(BaseHTTPMiddleware):
    """Extract user from Supabase JWT (Authorization: Bearer) and attach to request.state.user.

    - Supports JWKS verification using project ref if provided.
    - Falls back to HS256 secret if SUPABASE_JWT_SECRET is configured.
    - Only Google sign-in is expected on the frontend, but JWT verification is provider-agnostic.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._jwks_client: Optional[PyJWKClient] = None
        if settings.SUPABASE_PROJECT_REF:
            jwks_url = f"https://{settings.SUPABASE_PROJECT_REF}.supabase.co/auth/v1/keys"
            try:
                self._jwks_client = PyJWKClient(jwks_url)
            except Exception:
                self._jwks_client = None

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        user: Optional[Dict[str, Any]] = None
        auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            try:
                decoded = self._verify_jwt(token)
                user = self._extract_user(decoded)
            except Exception:
                user = None
        # Attach user (or None)
        request.state.user = user
        return await call_next(request)

    def _verify_jwt(self, token: str) -> Dict[str, Any]:
        options = {"verify_aud": bool(settings.SUPABASE_JWT_AUD), "verify_signature": True}
        audience = settings.SUPABASE_JWT_AUD or None

        # Prefer JWKS (GoTrue v2)
        if self._jwks_client is not None:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token).key
            return jwt.decode(token, signing_key, algorithms=["RS256", "ES256"], audience=audience, options=options)

        # Fallback HS256 secret if provided
        if settings.SUPABASE_JWT_SECRET:
            return jwt.decode(token, settings.SUPABASE_JWT_SECRET, algorithms=["HS256"], audience=audience, options=options)

        # Last resort: decode without verification (not recommended)
        return jwt.decode(token, options={"verify_signature": False, "verify_aud": False})

    def _extract_user(self, decoded: Dict[str, Any]) -> Dict[str, Any]:
        # Typical GoTrue claims include sub (user id), email, role, etc.
        user_id = str(decoded.get("sub") or decoded.get("user_id") or "").strip()
        email = decoded.get("email")
        provider = (decoded.get("provider") or decoded.get("app_metadata", {}).get("provider") or "").lower()
        # Enforce Google-only login if configured
        if settings.ALLOWED_AUTH_PROVIDERS and provider and provider not in settings.ALLOWED_AUTH_PROVIDERS:
            # Treat as unauthenticated if provider is not allowed
            return {"id": "", "email": None, "provider": provider, "claims": decoded}
        return {"id": user_id, "email": email, "provider": provider, "claims": decoded}


def add_auth(app: FastAPI) -> None:
    app.add_middleware(_SupabaseAuthMiddleware)
