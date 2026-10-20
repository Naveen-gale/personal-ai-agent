from fastapi.testclient import TestClient
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.config import Settings
from backend.app.main import app
from backend.app.security import create_session_token


def configure_settings(monkeypatch):
    values = {
        "MONGODB_URL": "mongodb://localhost:27017",
        "AGENT_SERVICE_URL": "http://localhost:8000",
        "AGENT_SERVICE_TOKEN": "agent-token-that-is-not-used-in-tests",
        "GOOGLE_CLIENT_ID": "test-client.apps.googleusercontent.com",
        "ALLOWED_GOOGLE_EMAIL": "owner@example.com",
        "SESSION_JWT_SECRET": "a-long-random-test-secret-that-exceeds-32-characters",
        "FRONTEND_ORIGINS": "http://localhost:5173",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return Settings.from_env()


def test_mongodb_url_accepts_legacy_env_key(monkeypatch):
    configure_settings(monkeypatch)
    monkeypatch.delenv("MONGODB_URL")
    monkeypatch.setenv("MONGO_DB_URL", "mongodb://legacy-name:27017")

    settings = Settings.from_env()

    assert settings.mongodb_url == "mongodb://legacy-name:27017"


def test_session_token_is_short_lived_and_scoped(monkeypatch):
    settings = configure_settings(monkeypatch)

    token = create_session_token("user-123", settings)

    import jwt

    claims = jwt.decode(
        token,
        settings.session_jwt_secret,
        algorithms=["HS256"],
        issuer="personal-ai-backend",
        audience="personal-ai-frontend",
    )
    assert claims["sub"] == "user-123"
    assert claims["exp"] - claims["iat"] == settings.session_ttl_seconds


def test_health_response_has_request_id():
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["x-request-id"]
    assert response.json()["service"] == "personal-ai-backend"


def test_public_config_returns_only_google_web_client_id(monkeypatch):
    settings = configure_settings(monkeypatch)
    app.state.settings = settings
    client = TestClient(app)

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {"google_client_id": settings.google_client_id}


def test_api_error_shape_is_consistent_for_unauthenticated_request():
    client = TestClient(app)

    response = client.get("/api/v1/me")
    data = response.json()

    assert response.status_code == 401
    assert data["success"] is False
    assert data["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert data["error"]["request_id"] == response.headers["x-request-id"]


def test_google_sign_in_creates_a_scoped_backend_session(monkeypatch):
    settings = configure_settings(monkeypatch)
    user = {
        "_id": "user-123",
        "email": "owner@example.com",
        "name": "Owner",
        "status": "active",
    }
    users = SimpleNamespace(find_one_and_update=AsyncMock(return_value=user))
    app.state.settings = settings
    app.state.database = SimpleNamespace(users=users)
    client = TestClient(app)

    with patch(
        "backend.app.main.verify_google_identity",
        new=AsyncMock(
            return_value={
                "google_sub": "google-user-123",
                "email": "owner@example.com",
                "name": "Owner",
            }
        ),
    ):
        response = client.post("/api/v1/auth/google", json={"credential": "x" * 30})

    assert response.status_code == 200
    assert response.json()["user"]["id"] == "user-123"
    assert response.json()["token_type"] == "Bearer"
    users.find_one_and_update.assert_awaited_once()


def test_session_authentication_loads_and_checks_the_active_user(monkeypatch):
    settings = configure_settings(monkeypatch)
    user = {
        "_id": "user-123",
        "email": "owner@example.com",
        "name": "Owner",
        "status": "active",
    }
    users = SimpleNamespace(find_one=AsyncMock(return_value=user))
    app.state.settings = settings
    app.state.database = SimpleNamespace(users=users)
    client = TestClient(app)

    response = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {create_session_token('user-123', settings)}"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "owner@example.com"
    users.find_one.assert_awaited_once_with({"_id": "user-123", "status": "active"})
