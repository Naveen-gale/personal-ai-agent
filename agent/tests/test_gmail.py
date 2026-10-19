"""
tests/test_gmail.py
--------------------
Unit tests for the Gmail service layer and LangChain tool definitions.

All tests use mocks to simulate Google API responses.
No real network calls, Google logins, or Groq API credits are required.

Run with:
    .\\agent\\.venv\\Scripts\\python.exe -m pytest agent\\tests\\test_gmail.py -v
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ══════════════════════════════════════════════════════════════════════════════
# 1. SERVICE LAYER TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestGmailService:
    """Tests for agent.services.gmail_service functions."""

    def test_search_messages_empty(self):
        """search_messages returns an empty list when no messages match."""
        mock_service = MagicMock()
        mock_service.users().messages().list().execute.return_value = {"messages": []}

        with patch("agent.services.gmail_service.create_gmail_client", return_value=mock_service):
            from agent.services.gmail_service import search_messages
            result = search_messages("is:unread", max_results=5)

        assert result == []

    def test_search_messages_formatted(self):
        """search_messages returns list of dicts with id, sender, subject, date, snippet."""
        mock_service = MagicMock()
        mock_service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg_001", "threadId": "th_001"}]
        }
        mock_service.users().messages().get().execute.return_value = {
            "id": "msg_001",
            "threadId": "th_001",
            "snippet": "Meeting at 10am",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Alice <alice@example.com>"},
                    {"name": "Subject", "value": "Project Update"},
                    {"name": "Date", "value": "Mon, 1 Jan 2026 10:00:00 +0000"},
                ]
            },
        }

        with patch("agent.services.gmail_service.create_gmail_client", return_value=mock_service):
            from agent.services.gmail_service import search_messages
            results = search_messages("in:inbox", max_results=1)

        assert len(results) == 1
        assert results[0]["id"] == "msg_001"
        assert results[0]["sender"] == "Alice <alice@example.com>"
        assert results[0]["subject"] == "Project Update"
        assert results[0]["snippet"] == "Meeting at 10am"

    def test_get_message_detail_decodes_body(self):
        """get_message_detail decodes plain text base64 payload."""
        import base64
        body_text = "Hello Alice, please submit the report by Friday."
        b64_body = base64.urlsafe_b64encode(body_text.encode("utf-8")).decode("utf-8")

        mock_service = MagicMock()
        mock_service.users().messages().get().execute.return_value = {
            "id": "msg_detail_1",
            "threadId": "th_detail_1",
            "snippet": "Hello Alice...",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "mimeType": "text/plain",
                "body": {"data": b64_body},
                "headers": [
                    {"name": "From", "value": "manager@company.com"},
                    {"name": "To", "value": "alice@company.com"},
                    {"name": "Subject", "value": "Report Deadline"},
                    {"name": "Date", "value": "Tue, 2 Jan 2026 09:00:00 +0000"},
                    {"name": "Message-ID", "value": "<m123@company.com>"},
                ],
            },
        }

        with patch("agent.services.gmail_service.create_gmail_client", return_value=mock_service):
            from agent.services.gmail_service import get_message_detail
            detail = get_message_detail("msg_detail_1")

        assert detail["id"] == "msg_detail_1"
        assert detail["sender"] == "manager@company.com"
        assert detail["subject"] == "Report Deadline"
        assert "Friday" in detail["body"]

    def test_validate_email_address(self):
        """validate_email_address validates correct addresses and rejects invalid formats."""
        from agent.services.gmail_service import validate_email_address

        # Valid addresses
        assert validate_email_address("user@example.com") == "user@example.com"
        assert validate_email_address("Alice Smith <alice@company.org>") == "Alice Smith <alice@company.org>"

        # Invalid addresses
        with pytest.raises(ValueError):
            validate_email_address("")
        with pytest.raises(ValueError):
            validate_email_address("invalid-email-no-at")
        with pytest.raises(ValueError):
            validate_email_address("someone@nodomain")

    def test_send_email_service(self):
        """send_email encodes MIME message and sends via messages.send()."""
        mock_service = MagicMock()
        mock_service.users().messages().send().execute.return_value = {
            "id": "sent_123",
            "threadId": "thread_123",
        }

        with patch("agent.services.gmail_service.create_gmail_client", return_value=mock_service):
            from agent.services.gmail_service import send_email
            result = send_email(to="recipient@example.com", subject="Test", body="Hello")

        assert result["id"] == "sent_123"
        assert result["to"] == "recipient@example.com"
        assert mock_service.users().messages().send.called

    def test_reply_to_message_preserves_thread_and_subject(self):
        """reply_to_message preserves threadId and prepends 'Re: ' to subject."""
        mock_detail = {
            "id": "orig_msg",
            "thread_id": "orig_th_777",
            "sender": "sender@example.com",
            "subject": "Original Topic",
            "message_id_header": "<orig777@example.com>",
            "references_header": "",
            "to": "me@example.com",
            "cc": "",
            "body": "Original body",
        }

        mock_service = MagicMock()
        mock_service.users().messages().send().execute.return_value = {
            "id": "reply_msg_999",
            "threadId": "orig_th_777",
        }

        with patch("agent.services.gmail_service.get_message_detail", return_value=mock_detail), \
             patch("agent.services.gmail_service.create_gmail_client", return_value=mock_service):
            from agent.services.gmail_service import reply_to_message
            res = reply_to_message(message_id="orig_msg", body="Thanks for the update.")

        assert res["id"] == "reply_msg_999"
        assert res["thread_id"] == "orig_th_777"
        assert res["subject"] == "Re: Original Topic"
        assert res["to"] == "sender@example.com"

        # Verify threadId was included in the send payload
        call_kwargs = mock_service.users().messages().send.call_args[1]
        assert call_kwargs["body"].get("threadId") == "orig_th_777"

    def test_trash_messages_never_calls_permanent_delete(self):
        """trash_messages calls messages().trash(), NEVER messages().delete()."""
        mock_service = MagicMock()
        mock_trash_method = mock_service.users().messages().trash
        mock_trash_method.return_value.execute.return_value = {}

        with patch("agent.services.gmail_service.create_gmail_client", return_value=mock_service):
            from agent.services.gmail_service import trash_messages
            count = trash_messages(["msg_a", "msg_b"])

        assert count == 2
        assert mock_trash_method.call_count == 2
        assert not hasattr(mock_service.users().messages(), "delete") or \
               not mock_service.users().messages().delete.called


# ══════════════════════════════════════════════════════════════════════════════
# 2. TOOL LAYER & CONFIRMATION SAFEGUARD TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestGmailTools:
    """Tests for agent.tools.gmail_tools LangChain tool functions."""

    def test_search_gmail_tool(self):
        """search_gmail returns formatted string with Message IDs."""
        fake_msgs = [
            {
                "id": "id_101",
                "thread_id": "th_101",
                "sender": "Alice <alice@test.com>",
                "subject": "Status Report",
                "date": "Mon, 1 Jan 2026",
                "snippet": "Here is the report...",
            }
        ]
        with patch("agent.services.gmail_service.search_messages", return_value=fake_msgs):
            from agent.tools.gmail_tools import search_gmail
            output = search_gmail.invoke({"query": "in:inbox", "max_results": 5})

        assert "id_101" in output
        assert "Alice <alice@test.com>" in output
        assert "Status Report" in output

    def test_read_email_tool(self):
        """read_email formats email headers and body clearly."""
        fake_detail = {
            "id": "read_001",
            "thread_id": "th_001",
            "sender": "Prof. Smith <prof@univ.edu>",
            "to": "student@univ.edu",
            "cc": "",
            "date": "Wed, 3 Jan 2026",
            "subject": "Final Assignment Due",
            "labels": ["INBOX", "UNREAD"],
            "body": "Your final assignment deadline is next Monday at 5pm.",
        }
        with patch("agent.services.gmail_service.get_message_detail", return_value=fake_detail):
            from agent.tools.gmail_tools import read_email
            output = read_email.invoke({"message_id": "read_001"})

        assert "read_001" in output
        assert "Prof. Smith" in output
        assert "Final Assignment Due" in output
        assert "next Monday at 5pm" in output

    def test_get_unread_emails_tool(self):
        """get_unread_emails retrieves unread emails with full contents."""
        fake_unread = [
            {
                "id": "unr_1",
                "sender": "HR <hr@work.com>",
                "date": "Thu, 4 Jan 2026",
                "subject": "Benefits Enrollment",
                "body": "Action required: enroll by Jan 15.",
            }
        ]
        with patch("agent.services.gmail_service.get_unread_messages", return_value=fake_unread):
            from agent.tools.gmail_tools import get_unread_emails
            output = get_unread_emails.invoke({"max_results": 5})

        assert "unr_1" in output
        assert "HR <hr@work.com>" in output
        assert "Benefits Enrollment" in output
        assert "Action required" in output

    def test_create_draft_tool(self):
        """create_draft creates a draft and returns confirmation without sending."""
        fake_draft = {"id": "draft_99", "to": "friend@example.com", "subject": "Hello"}
        with patch("agent.services.gmail_service.create_draft", return_value=fake_draft):
            from agent.tools.gmail_tools import create_draft
            output = create_draft.invoke({"to": "friend@example.com", "subject": "Hello", "body": "How are you?"})

        assert "Draft created successfully" in output
        assert "draft_99" in output
        assert "Drafts folder" in output

    def test_send_email_safeguard_blocks_until_confirmed(self):
        """
        CRITICAL TEST: send_email must NOT send when confirmed=False.
        It must display recipient, subject, and body, and request confirmation.
        """
        with patch("agent.services.gmail_service.send_email") as mock_send:
            from agent.tools.gmail_tools import send_email
            output = send_email.invoke({
                "to": "boss@example.com",
                "subject": "Weekly Update",
                "body": "Everything is on track.",
                "confirmed": False,
            })

        # Service was NOT called
        assert not mock_send.called, "send_email service must NOT be called when confirmed=False"

        # Output contains confirmation warning and full email preview
        assert "CONFIRMATION REQUIRED" in output
        assert "boss@example.com" in output
        assert "Weekly Update" in output
        assert "Everything is on track." in output

    def test_send_email_executes_when_confirmed(self):
        """send_email calls gmail_service.send_email when confirmed=True."""
        fake_sent = {"id": "msg_sent_77", "to": "boss@example.com", "subject": "Update"}
        with patch("agent.services.gmail_service.send_email", return_value=fake_sent) as mock_send:
            from agent.tools.gmail_tools import send_email
            from agent.tools.confirmation import authorize_tool_call
            with authorize_tool_call("send_email"):
                output = send_email.invoke({
                    "to": "boss@example.com",
                    "subject": "Update",
                    "body": "All done.",
                    "confirmed": True,
                })

        assert mock_send.called
        assert "Email sent successfully" in output
        assert "msg_sent_77" in output

    def test_send_email_validates_recipient(self):
        """send_email rejects invalid recipient address with validation error."""
        from agent.tools.gmail_tools import send_email
        output = send_email.invoke({
            "to": "invalid_email_format",
            "subject": "Subject",
            "body": "Body",
            "confirmed": True,
        })
        assert "Validation error" in output

    def test_reply_to_email_safeguard_blocks_until_confirmed(self):
        """reply_to_email must NOT send reply when confirmed=False."""
        fake_orig = {
            "id": "orig_42",
            "sender": "colleague@work.com",
            "subject": "Lunch Plans",
            "thread_id": "th_42",
        }
        with patch("agent.services.gmail_service.get_message_detail", return_value=fake_orig), \
             patch("agent.services.gmail_service.reply_to_message") as mock_reply:
            from agent.tools.gmail_tools import reply_to_email
            output = reply_to_email.invoke({
                "message_id": "orig_42",
                "body": "Sounds good, see you at noon.",
                "confirmed": False,
            })

        assert not mock_reply.called
        assert "CONFIRMATION REQUIRED" in output
        assert "colleague@work.com" in output
        assert "Lunch Plans" in output
        assert "Sounds good, see you at noon." in output

    def test_trash_messages_safeguard_blocks_until_confirmed(self):
        """trash_messages must NOT trash messages when confirmed=False."""
        with patch("agent.services.gmail_service.trash_messages") as mock_trash:
            from agent.tools.gmail_tools import trash_messages
            output = trash_messages.invoke({
                "message_ids": ["msg_1", "msg_2"],
                "confirmed": False,
            })

        assert not mock_trash.called
        assert "CONFIRMATION REQUIRED" in output
        assert "2 message(s)" in output

    def test_trash_messages_executes_when_confirmed(self):
        """trash_messages calls service when confirmed=True."""
        with patch("agent.services.gmail_service.trash_messages", return_value=2) as mock_trash:
            from agent.tools.gmail_tools import trash_messages
            from agent.tools.confirmation import authorize_tool_call
            with authorize_tool_call("trash_messages"):
                output = trash_messages.invoke({
                    "message_ids": ["msg_1", "msg_2"],
                    "confirmed": True,
                })

        assert mock_trash.called
        assert "Successfully moved 2 email(s) to Gmail Trash" in output

    def test_model_confirmation_argument_cannot_send_email(self):
        with patch("agent.services.gmail_service.send_email") as mock_send:
            from agent.tools.gmail_tools import send_email
            output = send_email.invoke({
                "to": "boss@example.com",
                "subject": "Update",
                "body": "All done.",
                "confirmed": True,
            })

        mock_send.assert_not_called()
        assert "CONFIRMATION REQUIRED" in output

    def test_mark_as_read_and_unread(self):
        """mark_as_read and mark_as_unread tools call label modifications."""
        with patch("agent.services.gmail_service.modify_message_labels", return_value=1):
            from agent.tools.gmail_tools import mark_as_read, mark_as_unread
            read_out = mark_as_read.invoke({"message_ids": ["msg_read_1"]})
            unread_out = mark_as_unread.invoke({"message_ids": ["msg_unread_1"]})

        assert "marked 1 email(s) as read" in read_out
        assert "marked 1 email(s) as unread" in unread_out

    def test_archive_messages(self):
        """archive_messages removes INBOX label."""
        with patch("agent.services.gmail_service.modify_message_labels", return_value=2):
            from agent.tools.gmail_tools import archive_messages
            output = archive_messages.invoke({"message_ids": ["m1", "m2"]})

        assert "Successfully archived 2 email(s)" in output

    def test_label_creation_and_application(self):
        """create_label and apply_label call service and report success."""
        with patch("agent.services.gmail_service.get_or_create_label", return_value="lbl_123"), \
             patch("agent.services.gmail_service.modify_message_labels", return_value=1):
            from agent.tools.gmail_tools import create_label, apply_label
            create_out = create_label.invoke({"label_name": "Invoices"})
            apply_out = apply_label.invoke({"message_ids": ["msg_inv_1"], "label_name": "Invoices"})

        assert "Invoices" in create_out
        assert "lbl_123" in create_out
        assert "Successfully applied label 'Invoices' to 1 message(s)" in apply_out

    def test_failed_api_call_reported_as_error_not_success(self):
        """When the service raises an error, the tool reports an error message, never success."""
        with patch(
            "agent.services.gmail_service.search_messages",
            side_effect=RuntimeError("Google quota exceeded"),
        ):
            from agent.tools.gmail_tools import search_gmail
            output = search_gmail.invoke({"query": "test"})

        assert "Gmail search error" in output
        assert "quota exceeded" in output


# ══════════════════════════════════════════════════════════════════════════════
# 3. AUTHENTICATION TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestGmailAuth:
    """Tests for agent.auth.gmail_auth.get_credentials."""

    def test_raises_file_not_found_when_credentials_missing(self, tmp_path, monkeypatch):
        """get_credentials raises FileNotFoundError if credentials.json is absent."""
        import agent.auth.gmail_auth as auth_mod
        monkeypatch.setattr(auth_mod, "CREDENTIALS_FILE", tmp_path / "credentials.json")
        monkeypatch.setattr(auth_mod, "TOKEN_FILE", tmp_path / "token.json")

        with pytest.raises(FileNotFoundError, match="credentials.json"):
            auth_mod.get_credentials()

    def test_loads_and_returns_valid_token(self, tmp_path, monkeypatch):
        """get_credentials returns credentials when valid token.json exists."""
        import agent.auth.gmail_auth as auth_mod

        fake_token = {
            "token": "fake_access_token",
            "refresh_token": "fake_refresh_token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "fake_client_id",
            "client_secret": "fake_client_secret",
            "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
        }
        token_file = tmp_path / "token.json"
        token_file.write_text(json.dumps(fake_token), encoding="utf-8")
        cred_file = tmp_path / "credentials.json"
        cred_file.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(auth_mod, "CREDENTIALS_FILE", cred_file)
        monkeypatch.setattr(auth_mod, "TOKEN_FILE", token_file)

        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_creds.valid = True
        mock_creds.scopes = auth_mod.GMAIL_SCOPES

        with patch("agent.auth.gmail_auth.Credentials.from_authorized_user_file", return_value=mock_creds):
            result = auth_mod.get_credentials()

        assert result is mock_creds
