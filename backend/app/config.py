"""Validated runtime configuration for the central backend."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class Settings:
    mongodb_url: str
    database_name: str
    agent_service_url: str
    agent_service_token: str
    agent_timeout_seconds: float
    google_client_id: str
    allowed_google_email: str
    session_jwt_secret: str
    session_ttl_seconds: int
    frontend_origins: tuple[str, ...]
    max_request_body_bytes: int

    @classmethod
    def from_env(cls) -> "Settings":
        required = {
            "MONGODB_URL": os.getenv("MONGODB_URL", "").strip(),
            "AGENT_SERVICE_URL": os.getenv("AGENT_SERVICE_URL", "").strip(),
            "AGENT_SERVICE_TOKEN": os.getenv("AGENT_SERVICE_TOKEN", "").strip(),
            "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
            "ALLOWED_GOOGLE_EMAIL": os.getenv("ALLOWED_GOOGLE_EMAIL", "").strip(),
            "SESSION_JWT_SECRET": os.getenv("SESSION_JWT_SECRET", "").strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing required backend configuration: {', '.join(missing)}")

        if len(required["AGENT_SERVICE_TOKEN"]) < 32:
            raise ValueError("AGENT_SERVICE_TOKEN must contain at least 32 characters.")
        secret = required["SESSION_JWT_SECRET"]
        if len(secret) < 32:
            raise ValueError("SESSION_JWT_SECRET must contain at least 32 characters.")

        origins = tuple(
            origin.strip()
            for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",")
            if origin.strip()
        )
        if not origins or "*" in origins:
            raise ValueError("FRONTEND_ORIGINS must contain explicit trusted origins, not '*'.")
        agent_timeout_seconds = float(os.getenv("AGENT_TIMEOUT_SECONDS", "45"))
        session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
        max_request_body_bytes = int(os.getenv("MAX_REQUEST_BODY_BYTES", "31457280"))
        if agent_timeout_seconds <= 0 or session_ttl_seconds <= 0 or max_request_body_bytes <= 0:
            raise ValueError("Timeout, token lifetime, and request-size settings must be positive.")
        return cls(
            mongodb_url=required["MONGODB_URL"],
            database_name=os.getenv("DATABASE_NAME", "personal_agent").strip(),
            agent_service_url=required["AGENT_SERVICE_URL"].rstrip("/"),
            agent_service_token=required["AGENT_SERVICE_TOKEN"],
            agent_timeout_seconds=agent_timeout_seconds,
            google_client_id=required["GOOGLE_CLIENT_ID"],
            allowed_google_email=required["ALLOWED_GOOGLE_EMAIL"].casefold(),
            session_jwt_secret=secret,
            session_ttl_seconds=session_ttl_seconds,
            frontend_origins=origins,
            max_request_body_bytes=max_request_body_bytes,
        )
