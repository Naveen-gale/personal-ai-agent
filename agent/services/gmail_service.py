"""
services/gmail_service.py
--------------------------
Gmail API service layer.

Responsibilities:
  - Create and manage the authenticated Gmail API client.
  - Search messages using Gmail query syntax.
  - Retrieve full email details including headers and decoded message body.
  - Create email drafts.
  - Send new emails and threaded replies.
  - Modify message labels (mark read/unread, archive, custom labels).
  - Move messages to Gmail Trash (never permanently delete).
  - Create and manage user labels.
  - Handle Gmail API errors and report them cleanly.

Design note:
  This service layer has NO dependency on LangChain or LangGraph.
  It interacts solely with the Google API client and the standard library,
  making it easy to test with standard Python mocks.
"""

import base64
import re
from email.message import EmailMessage
from email.utils import parseaddr

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.auth.gmail_auth import get_credentials


# ── Client Construction ───────────────────────────────────────────────────────

def create_gmail_client():
    """
    Build and return an authorized Google API Resource object for the Gmail v1 API.

    Returns:
        A Google API Resource object.

    Raises:
        RuntimeError: If authentication fails or credentials cannot be obtained.
    """
    credentials = get_credentials()
    return build("gmail", "v1", credentials=credentials)


# ── Body Extraction and Formatting Helpers ────────────────────────────────────

def _extract_body_from_payload(payload: dict) -> str:
    """
    Recursively extract readable text content from a Gmail message payload.

    Handles plain text, HTML (cleaned of tags), and multipart MIME structures.
    """
    mime_type = payload.get("mimeType", "")
    body_data = payload.get("body", {}).get("data", "")

    # Direct plain text body
    if body_data and mime_type == "text/plain":
        try:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace").strip()
        except Exception:
            pass

    # HTML fallback if no plain text
    html_fallback = ""
    if body_data and mime_type == "text/html":
        try:
            html_fallback = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")
        except Exception:
            pass

    # Inspect multipart parts recursively
    parts = payload.get("parts", [])
    for part in parts:
        part_type = part.get("mimeType", "")
        part_data = part.get("body", {}).get("data", "")

        if part_type == "text/plain" and part_data:
            try:
                return base64.urlsafe_b64decode(part_data).decode("utf-8", errors="replace").strip()
            except Exception:
                pass
        elif part.get("parts"):
            nested_text = _extract_body_from_payload(part)
            if nested_text:
                return nested_text
        elif part_type == "text/html" and part_data and not html_fallback:
            try:
                html_fallback = base64.urlsafe_b64decode(part_data).decode("utf-8", errors="replace")
            except Exception:
                pass

    if html_fallback:
        # Strip script and style blocks, then strip HTML tags for clean text
        cleaned = re.sub(r"<style.*?</style>", "", html_fallback, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<script.*?</script>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"&nbsp;", " ", cleaned)
        cleaned = re.sub(r"&amp;", "&", cleaned)
        cleaned = re.sub(r"&lt;", "<", cleaned)
        cleaned = re.sub(r"&gt;", ">", cleaned)
        # Strip zero-width/invisible unicode characters frequently found in marketing emails
        cleaned = re.sub(r"[\u200b-\u200f\ufeff\u034f\u200c\u200d\xa0]+", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    return ""


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    """Convert a Gmail API header list into a lowercased dictionary."""
    return {h.get("name", "").lower(): h.get("value", "") for h in headers if "name" in h}


# ── Recipient Validation Helper ───────────────────────────────────────────────

def validate_email_address(email_str: str) -> str:
    """
    Validate and return a clean email address string.

    Supports formats like 'user@example.com' or 'Name <user@example.com>'.

    Raises:
        ValueError: If the email address format is invalid.
    """
    if not email_str or not isinstance(email_str, str):
        raise ValueError("Recipient email address cannot be empty.")

    clean_str = email_str.strip()
    _, addr = parseaddr(clean_str)
    target = addr if addr else clean_str

    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(pattern, target):
        raise ValueError(
            f"Invalid recipient email address format: '{email_str}'. "
            "Expected a valid address such as 'user@example.com'."
        )

    return clean_str


# ── Search and Retrieval ──────────────────────────────────────────────────────

def search_messages(query: str = "in:inbox", max_results: int = 5) -> list[dict]:
    """
    Search Gmail messages and return summary dictionaries.

    Args:
        query: Gmail query string (e.g. 'in:inbox', 'is:unread', 'from:alice@example.com').
        max_results: Max messages to return (capped between 1 and 20).

    Returns:
        A list of dicts with keys: id, thread_id, sender, subject, date, snippet.
    """
    max_results = max(1, min(max_results, 20))
    service = create_gmail_client()

    try:
        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
    except HttpError as api_error:
        raise RuntimeError(f"Gmail API error while searching: {api_error}") from api_error

    stubs = response.get("messages", [])
    if not stubs:
        return []

    results = []
    for stub in stubs:
        try:
            msg = (
                service.users()
                .messages()
                .get(
                    userId="me",
                    id=stub["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                )
                .execute()
            )
        except HttpError:
            continue

        header_map = _parse_headers(msg.get("payload", {}).get("headers", []))

        results.append(
            {
                "id": stub["id"],
                "thread_id": msg.get("threadId", stub.get("threadId", "")),
                "sender": header_map.get("from", "Unknown sender"),
                "subject": header_map.get("subject", "(No subject)"),
                "date": header_map.get("date", "Unknown date"),
                "snippet": msg.get("snippet", ""),
            }
        )

    return results


def get_message_detail(message_id: str) -> dict:
    """
    Retrieve full details of a specific message by its Gmail message ID.

    Returns:
        Dict with keys: id, thread_id, sender, to, cc, subject, date, snippet, body, labels.
    """
    if not message_id or not isinstance(message_id, str):
        raise ValueError("message_id must be a non-empty string.")

    service = create_gmail_client()

    try:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
    except HttpError as api_error:
        raise RuntimeError(f"Failed to retrieve message '{message_id}': {api_error}") from api_error

    payload = msg.get("payload", {})
    headers = _parse_headers(payload.get("headers", []))
    body = _extract_body_from_payload(payload)

    # Fall back to snippet if no body could be decoded
    if not body:
        body = msg.get("snippet", "(Empty message body)")

    # Cap message body to 2000 characters to stay within model token-per-minute limits
    if len(body) > 2000:
        body = body[:2000] + "\n\n[...Message excerpt truncated to stay within rate limits. Full email is available in Gmail.]"

    return {
        "id": msg.get("id", message_id),
        "thread_id": msg.get("threadId", ""),
        "sender": headers.get("from", "Unknown sender"),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "subject": headers.get("subject", "(No subject)"),
        "date": headers.get("date", "Unknown date"),
        "snippet": msg.get("snippet", ""),
        "body": body,
        "labels": msg.get("labelIds", []),
        "message_id_header": headers.get("message-id", ""),
        "references_header": headers.get("references", ""),
    }


def get_unread_messages(max_results: int = 5) -> list[dict]:
    """
    Retrieve unread inbox emails with clean, concise message excerpts.

    Args:
        max_results: Max unread messages to retrieve (capped between 1 and 5).

    Returns:
        List of message detail dictionaries.
    """
    max_results = max(1, min(max_results, 5))
    summaries = search_messages(query="is:unread in:inbox", max_results=max_results)

    detailed_messages = []
    for s in summaries:
        try:
            detail = get_message_detail(s["id"])
            # Cap each unread email body excerpt to 400 chars for summarization efficiency
            raw_body = detail.get("body", "")
            if len(raw_body) > 400:
                detail["body"] = raw_body[:400] + "... [truncated]"
            detailed_messages.append(detail)
        except Exception:
            # Fall back to summary if full get fails
            detailed_messages.append(s)

    return detailed_messages


# ── Drafting and Sending ──────────────────────────────────────────────────────

def create_draft(to: str, subject: str, body: str) -> dict:
    """
    Create a new draft in Gmail without sending it.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body content.

    Returns:
        Dict with keys: id, to, subject.
    """
    valid_to = validate_email_address(to)
    if not subject:
        raise ValueError("Subject cannot be empty.")
    if not body:
        raise ValueError("Body cannot be empty.")

    service = create_gmail_client()

    message = EmailMessage()
    message.set_content(body)
    message["To"] = valid_to
    message["Subject"] = subject

    raw_bytes = message.as_bytes()
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    try:
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": encoded}})
            .execute()
        )
    except HttpError as api_error:
        raise RuntimeError(f"Gmail API error while creating draft: {api_error}") from api_error

    return {
        "id": draft.get("id", ""),
        "to": valid_to,
        "subject": subject,
    }


def send_email(to: str, subject: str, body: str) -> dict:
    """
    Send an email via the Gmail API.

    Args:
        to: Recipient email address.
        subject: Email subject line.
        body: Email body content.

    Returns:
        Dict with keys: id, thread_id, to, subject.
    """
    valid_to = validate_email_address(to)
    if not subject:
        raise ValueError("Subject cannot be empty.")
    if not body:
        raise ValueError("Body cannot be empty.")

    service = create_gmail_client()

    message = EmailMessage()
    message.set_content(body)
    message["To"] = valid_to
    message["Subject"] = subject

    raw_bytes = message.as_bytes()
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    try:
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": encoded})
            .execute()
        )
    except HttpError as api_error:
        raise RuntimeError(f"Gmail API error while sending email: {api_error}") from api_error

    return {
        "id": sent.get("id", ""),
        "thread_id": sent.get("threadId", ""),
        "to": valid_to,
        "subject": subject,
    }


def reply_to_message(message_id: str, body: str, reply_all: bool = False) -> dict:
    """
    Reply to an existing email, preserving the thread ID, recipient, and subject.

    Args:
        message_id: ID of the original message to reply to.
        body: Reply message body.
        reply_all: If True, include original CC recipients.

    Returns:
        Dict with keys: id, thread_id, to, subject.
    """
    if not body:
        raise ValueError("Reply body cannot be empty.")

    # Step 1: Retrieve the original message details to get headers and threadId
    original = get_message_detail(message_id)

    reply_to = original.get("sender", "")
    if not reply_to:
        raise ValueError(f"Could not determine sender for message '{message_id}'.")

    # Determine subject: prepend 'Re: ' if not already present
    orig_subject = original.get("subject", "")
    if not orig_subject.lower().startswith("re:"):
        reply_subject = f"Re: {orig_subject}"
    else:
        reply_subject = orig_subject

    thread_id = original.get("thread_id", "")
    orig_msg_id = original.get("message_id_header", "")
    orig_refs = original.get("references_header", "")

    # Build RFC 2822 References header
    if orig_refs and orig_msg_id:
        new_refs = f"{orig_refs} {orig_msg_id}"
    elif orig_msg_id:
        new_refs = orig_msg_id
    else:
        new_refs = ""

    service = create_gmail_client()

    message = EmailMessage()
    message.set_content(body)
    message["To"] = reply_to
    message["Subject"] = reply_subject

    if reply_all and original.get("cc"):
        message["Cc"] = original["cc"]

    if orig_msg_id:
        message["In-Reply-To"] = orig_msg_id
    if new_refs:
        message["References"] = new_refs

    raw_bytes = message.as_bytes()
    encoded = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")

    send_payload = {"raw": encoded}
    if thread_id:
        send_payload["threadId"] = thread_id

    try:
        sent = (
            service.users()
            .messages()
            .send(userId="me", body=send_payload)
            .execute()
        )
    except HttpError as api_error:
        raise RuntimeError(f"Gmail API error while sending reply: {api_error}") from api_error

    return {
        "id": sent.get("id", ""),
        "thread_id": sent.get("threadId", thread_id),
        "to": reply_to,
        "subject": reply_subject,
    }


# ── Label and Organization Operations ─────────────────────────────────────────

def modify_message_labels(
    message_ids: list[str],
    add_labels: list[str] = None,
    remove_labels: list[str] = None,
) -> int:
    """
    Add or remove labels from one or more messages.

    Args:
        message_ids: List of Gmail message IDs to modify.
        add_labels: Label IDs to add (e.g. ['UNREAD']).
        remove_labels: Label IDs to remove (e.g. ['INBOX', 'UNREAD']).

    Returns:
        Count of successfully modified messages.
    """
    if not message_ids:
        raise ValueError("message_ids list cannot be empty.")

    # Limit batch modifications to 20 messages for safety
    if len(message_ids) > 20:
        raise ValueError(
            f"Cannot modify {len(message_ids)} messages at once. Limit is 20."
        )

    service = create_gmail_client()
    body = {
        "addLabelIds": add_labels or [],
        "removeLabelIds": remove_labels or [],
    }

    try:
        if len(message_ids) == 1:
            service.users().messages().modify(
                userId="me",
                id=message_ids[0],
                body=body,
            ).execute()
        else:
            service.users().messages().batchModify(
                userId="me",
                body={"ids": message_ids, **body},
            ).execute()
    except HttpError as api_error:
        raise RuntimeError(f"Gmail API error modifying labels: {api_error}") from api_error

    return len(message_ids)


def trash_messages(message_ids: list[str]) -> int:
    """
    Move specified messages to Gmail Trash.

    NOTE: This does NOT permanently delete messages. Trashed messages
    remain in Gmail Trash for 30 days and can be recovered by the user.

    Args:
        message_ids: List of message IDs to move to trash (limit: 10).

    Returns:
        Count of messages moved to trash.
    """
    if not message_ids:
        raise ValueError("message_ids list cannot be empty.")

    if len(message_ids) > 10:
        raise ValueError(
            f"Bulk trash limit exceeded: {len(message_ids)} messages requested. Maximum allowed is 10."
        )

    service = create_gmail_client()
    trashed_count = 0

    for msg_id in message_ids:
        try:
            service.users().messages().trash(userId="me", id=msg_id).execute()
            trashed_count += 1
        except HttpError as api_error:
            raise RuntimeError(
                f"Gmail API error while trashing message '{msg_id}': {api_error}"
            ) from api_error

    return trashed_count


def get_or_create_label(label_name: str) -> str:
    """
    Look up an existing user label by name or create it if not found.

    Args:
        label_name: Human-readable label name (e.g. 'Project Alpha').

    Returns:
        The Gmail label ID string.
    """
    if not label_name or not isinstance(label_name, str):
        raise ValueError("label_name must be a non-empty string.")

    service = create_gmail_client()

    try:
        response = service.users().labels().list(userId="me").execute()
        labels = response.get("labels", [])

        # Check for case-insensitive match
        for label in labels:
            if label.get("name", "").strip().lower() == label_name.strip().lower():
                return label.get("id", "")

        # Label doesn't exist — create it
        new_label = (
            service.users()
            .labels()
            .create(
                userId="me",
                body={
                    "name": label_name.strip(),
                    "labelListVisibility": "labelShow",
                    "messageListVisibility": "show",
                },
            )
            .execute()
        )
        return new_label.get("id", "")
    except HttpError as api_error:
        raise RuntimeError(f"Gmail API error for label '{label_name}': {api_error}") from api_error
