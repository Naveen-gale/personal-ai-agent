"""Validated external request and response schemas."""

from pydantic import BaseModel, Field, model_validator


class GoogleSignInRequest(BaseModel):
    credential: str = Field(min_length=20, max_length=10_000)


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=20_000)
    idempotency_key: str = Field(min_length=8, max_length=120)
    attachments: list[dict[str, str]] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_attachments(self):
        total_chars = 0
        for attachment in self.attachments:
            if not attachment.get("name", "").strip():
                raise ValueError("Each attachment requires a name.")
            total_chars += len(attachment.get("text", ""))
        if total_chars > 500_000:
            raise ValueError("Extracted attachment text exceeds the chat processing limit.")
        return self


class ConfirmationRequest(BaseModel):
    confirmation_id: str = Field(min_length=16, max_length=80)
    decision: str


class ConversationCreateRequest(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_title(self):
        if not self.title.strip():
            raise ValueError("Conversation title cannot be blank.")
        return self
