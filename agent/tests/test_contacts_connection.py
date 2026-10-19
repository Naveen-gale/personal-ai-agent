"""Unit tests for Google Contacts authentication and client construction."""

from unittest.mock import MagicMock, patch

import pytest

from agent.auth.gmail_auth import (
    ALL_SCOPES,
    CALENDAR_SCOPES,
    CONTACTS_SCOPES,
    GMAIL_SCOPES,
    TASKS_SCOPES,
)
from agent.services import contacts_service


def test_contacts_use_the_existing_agent_oauth_files():
    import agent.auth.gmail_auth as auth

    assert auth.CREDENTIALS_FILE.parent == auth.AGENT_DIR
    assert auth.TOKEN_FILE.parent == auth.AGENT_DIR
    assert auth.CREDENTIALS_FILE.name == "credentials.json"
    assert auth.TOKEN_FILE.name == "token.json"
    assert contacts_service.TOKEN_FILE == auth.TOKEN_FILE


def test_oauth_scope_set_preserves_gmail_and_includes_contacts():
    assert GMAIL_SCOPES == ["https://www.googleapis.com/auth/gmail.modify"]
    assert set(CONTACTS_SCOPES) == {
        "https://www.googleapis.com/auth/contacts.readonly",
        "https://www.googleapis.com/auth/contacts",
    }
    assert set(GMAIL_SCOPES + CONTACTS_SCOPES).issubset(set(ALL_SCOPES))
    assert set(CALENDAR_SCOPES).issubset(set(ALL_SCOPES))
    assert set(TASKS_SCOPES).issubset(set(ALL_SCOPES))


def test_contacts_client_uses_shared_token_and_people_api():
    credentials = MagicMock()
    expected_service = MagicMock()

    with patch(
        "agent.services.contacts_service.get_credentials",
        return_value=credentials,
    ) as get_credentials, patch(
        "agent.services.contacts_service.build",
        return_value=expected_service,
    ) as build:
        result = contacts_service.get_contacts_service()

    assert result is expected_service
    get_credentials.assert_called_once_with(required_scopes=CONTACTS_SCOPES)
    build.assert_called_once_with(
        "people",
        "v1",
        credentials=credentials,
        cache_discovery=False,
    )


def test_contacts_auth_rejects_a_token_missing_contacts_scopes(tmp_path, monkeypatch):
    import agent.auth.gmail_auth as auth

    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth, "TOKEN_FILE", token_file)
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    credentials = MagicMock()
    credentials.valid = True
    credentials.expired = False
    credentials.scopes = GMAIL_SCOPES
    with patch(
        "agent.auth.gmail_auth.Credentials.from_authorized_user_file",
        return_value=credentials,
    ), patch(
        "agent.auth.gmail_auth.InstalledAppFlow.from_client_secrets_file"
    ) as auth_flow:
        with pytest.raises(RuntimeError, match="missing required scopes") as error:
            auth.get_credentials(required_scopes=ALL_SCOPES)

    assert "python -m agent.auth.gmail_auth" in str(error.value)
    auth_flow.assert_not_called()


def test_gmail_can_still_use_existing_gmail_only_token(tmp_path, monkeypatch):
    import agent.auth.gmail_auth as auth

    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth, "TOKEN_FILE", token_file)
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    credentials = MagicMock()
    credentials.valid = True
    credentials.expired = False
    credentials.scopes = GMAIL_SCOPES
    with patch(
        "agent.auth.gmail_auth.Credentials.from_authorized_user_file",
        return_value=credentials,
    ):
        assert auth.get_credentials() is credentials


def test_refresh_failure_is_actionable_without_exposing_token(tmp_path, monkeypatch):
    import agent.auth.gmail_auth as auth

    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth, "TOKEN_FILE", token_file)
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    credentials = MagicMock()
    credentials.valid = False
    credentials.expired = True
    credentials.refresh_token = "must-not-appear"
    credentials.scopes = ALL_SCOPES
    credentials.refresh.side_effect = RuntimeError("sensitive refresh details")
    with patch(
        "agent.auth.gmail_auth.Credentials.from_authorized_user_file",
        return_value=credentials,
    ), patch("agent.auth.gmail_auth.Request"):
        with pytest.raises(RuntimeError, match="token refresh failed") as error:
            auth.get_credentials(required_scopes=ALL_SCOPES)

    assert "must-not-appear" not in str(error.value)
    assert "sensitive refresh details" not in str(error.value)


def test_explicit_reauthorization_requests_all_scopes(tmp_path, monkeypatch):
    import agent.auth.gmail_auth as auth

    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")
    token_file = tmp_path / "token.json"
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)
    monkeypatch.setattr(auth, "TOKEN_FILE", token_file)

    authorized_credentials = MagicMock()
    authorized_credentials.scopes = ALL_SCOPES
    authorized_credentials.to_json.return_value = '{"authorized": true}'
    flow = MagicMock()
    flow.run_local_server.return_value = authorized_credentials
    with patch(
        "agent.auth.gmail_auth.InstalledAppFlow.from_client_secrets_file",
        return_value=flow,
    ) as create_flow:
        assert auth.get_credentials(force_reauth=True) is authorized_credentials

    create_flow.assert_called_once_with(str(credentials_file), scopes=ALL_SCOPES)
    assert token_file.read_text(encoding="utf-8") == '{"authorized": true}'


def test_expired_token_refreshes_and_persists_updated_credentials(
    tmp_path, monkeypatch
):
    import agent.auth.gmail_auth as auth

    token_file = tmp_path / "token.json"
    token_file.write_text("{}", encoding="utf-8")
    credentials_file = tmp_path / "credentials.json"
    credentials_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(auth, "TOKEN_FILE", token_file)
    monkeypatch.setattr(auth, "CREDENTIALS_FILE", credentials_file)

    credentials = MagicMock()
    credentials.valid = True
    credentials.expired = True
    credentials.refresh_token = "redacted"
    credentials.scopes = ALL_SCOPES
    credentials.to_json.return_value = '{"refreshed": true}'
    with patch(
        "agent.auth.gmail_auth.Credentials.from_authorized_user_file",
        return_value=credentials,
    ), patch("agent.auth.gmail_auth.Request") as request:
        assert auth.get_credentials(required_scopes=ALL_SCOPES) is credentials

    credentials.refresh.assert_called_once_with(request.return_value)
    assert token_file.read_text(encoding="utf-8") == '{"refreshed": true}'
