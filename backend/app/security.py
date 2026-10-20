"""Google ID-token verification and short-lived backend session tokens."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from backend.app.config import Settings


bearer_scheme = HTTPBearer(auto_error=False)


async def verify_google_identity(credential: str, settings: Settings) -> dict[str, str]:
    claims = await asyncio.to_thread(
        id_token.verify_oauth2_token,
        credential,
        GoogleRequest(),
        settings.google_client_id,
    )
    email = str(claims.get("email", "")).casefold()
    if not claims.get("sub") or claims.get("email_verified") is not True:
        raise ValueError("Google account email must be verified.")
    if email != settings.allowed_google_email:
        raise PermissionError("This Google account is not allowed to use this personal agent.")
    return {
        "google_sub": str(claims["sub"]),
        "email": email,
        "name": str(claims.get("name") or email),
    }


def create_session_token(user_id: str, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(seconds=settings.session_ttl_seconds),
        "jti": uuid4().hex,
        "iss": "personal-ai-backend",
        "aud": "personal-ai-frontend",
    }
    return jwt.encode(payload, settings.session_jwt_secret, algorithm="HS256")


async def require_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(status_code=401, detail="Sign in is required.")
    settings: Settings = request.app.state.settings
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.session_jwt_secret,
            algorithms=["HS256"],
            issuer="personal-ai-backend",
            audience="personal-ai-frontend",
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Your session expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Your session is invalid. Sign in again.") from exc
    user = await request.app.state.database.users.find_one(
        {"_id": payload.get("sub"), "status": "active"}
    )
    if not user:
        raise HTTPException(status_code=401, detail="The signed-in user is unavailable.")
    return user
