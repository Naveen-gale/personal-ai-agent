import pytest
from pydantic import ValidationError

from backend.app.schemas import ChatRequest, ConversationCreateRequest


def test_chat_request_limits_attachment_count_and_text():
    with pytest.raises(ValidationError):
        ChatRequest(
            message="Summarize these files",
            idempotency_key="request-key-123",
            attachments=[{"name": "large.txt", "text": "x" * 500_001}],
        )


def test_chat_request_rejects_blank_attachment_names():
    with pytest.raises(ValidationError):
        ChatRequest(
            message="Summarize this",
            idempotency_key="request-key-123",
            attachments=[{"name": " ", "text": "content"}],
        )


def test_conversation_title_cannot_be_blank():
    with pytest.raises(ValidationError):
        ConversationCreateRequest(title="   ")
