"""
tools/gmail_tools.py
---------------------
LangChain tool definitions for the Gmail assistant.

Responsibilities:
  - Expose validated, LangChain-compatible @tool functions to the LangGraph agent.
  - Implement confirmation safeguards for sending, replying, and trashing.
  - Keep docstrings concise to optimize LLM token usage and stay within TPM limits.
  - Delegate all actual API calls to services/gmail_service.py.
"""

from typing import Union
from langchain_core.tools import tool

from agent.services import gmail_service
from agent.tools.confirmation import consume_tool_authorization


def _normalize_id_list(ids: Union[list[str], str]) -> list[str]:
    """Normalize a message ID or list of IDs into a list of non-empty strings."""
    if isinstance(ids, str):
        return [i.strip() for i in ids.split(",") if i.strip()]
    elif isinstance(ids, list):
        return [str(i).strip() for i in ids if str(i).strip()]
    return []


# ── 1. Search Messages ────────────────────────────────────────────────────────

@tool
def search_gmail(query: str = "in:inbox", max_results: int = 5) -> str:
    """Search Gmail with queries like 'in:inbox', 'is:unread', 'from:name@domain.com', or 'subject:topic'."""
    try:
        messages = gmail_service.search_messages(query=query, max_results=max_results)
    except RuntimeError as err:
        return f"Gmail search error: {err}"

    if not messages:
        return f"No emails found matching search query: '{query}'"

    blocks = []
    for msg in messages:
        block = (
            f"Message ID: {msg['id']}\n"
            f"From:       {msg['sender']}\n"
            f"Subject:    {msg['subject']}\n"
            f"Date:       {msg['date']}\n"
            f"Snippet:    {msg['snippet']}"
        )
        blocks.append(block)

    return f"Found {len(messages)} email(s):\n\n" + "\n\n---\n\n".join(blocks)


# ── 2. Read Full Email ────────────────────────────────────────────────────────

@tool
def read_email(message_id: str) -> str:
    """Retrieve full headers and body of an email by its message_id."""
    clean_id = str(message_id).strip()
    if not clean_id:
        return "Error: message_id cannot be empty."

    try:
        detail = gmail_service.get_message_detail(clean_id)
    except (RuntimeError, ValueError) as err:
        return f"Error retrieving email '{clean_id}': {err}"

    labels_str = ", ".join(detail.get("labels", []))
    output = (
        f"Message ID: {detail['id']}\n"
        f"From:       {detail['sender']}\n"
        f"To:         {detail['to']}\n"
    )
    if detail.get("cc"):
        output += f"Cc:         {detail['cc']}\n"

    output += (
        f"Date:       {detail['date']}\n"
        f"Subject:    {detail['subject']}\n"
        f"Labels:     {labels_str}\n"
        f"\n--- Email Body ---\n"
        f"{detail['body']}\n"
        f"--- End of Email ---"
    )
    return output


# ── 3. Retrieve Unread Emails ─────────────────────────────────────────────────

@tool
def get_unread_emails(max_results: int = 3) -> str:
    """Retrieve recent unread inbox email excerpts to summarize and check for deadlines (max_results: 1 to 5)."""
    try:
        messages = gmail_service.get_unread_messages(max_results=max_results)
    except RuntimeError as err:
        return f"Error retrieving unread emails: {err}"

    if not messages:
        return "You have no unread emails in your inbox."

    blocks = []
    for idx, msg in enumerate(messages, 1):
        block = (
            f"[{idx}] Message ID: {msg['id']}\n"
            f"    From:    {msg['sender']}\n"
            f"    Date:    {msg['date']}\n"
            f"    Subject: {msg['subject']}\n"
            f"    Excerpt: {msg.get('body', msg.get('snippet', ''))}"
        )
        blocks.append(block)

    return f"Retrieved {len(messages)} unread email(s):\n\n" + "\n\n---\n\n".join(blocks)


# ── 4. Create Draft ───────────────────────────────────────────────────────────

@tool
def create_draft(to: str, subject: str, body: str) -> str:
    """Create a new email draft in Gmail without sending it. Args: to, subject, body."""
    try:
        draft = gmail_service.create_draft(to=to, subject=subject, body=body)
        return (
            f"Draft created successfully!\n"
            f"Draft ID:  {draft['id']}\n"
            f"To:        {draft['to']}\n"
            f"Subject:   {draft['subject']}\n"
            f"Status:    Saved in your Gmail Drafts folder."
        )
    except (ValueError, RuntimeError) as err:
        return f"Failed to create draft: {err}"


# ── 5. Send Email (With Safeguard) ────────────────────────────────────────────

@tool
def send_email(to: str, subject: str, body: str, confirmed: bool = False) -> str:
    """Send an email to a recipient. Set confirmed=True ONLY after explicit user confirmation."""
    try:
        valid_to = gmail_service.validate_email_address(to)
    except ValueError as val_err:
        return f"Validation error: {val_err}"

    if not subject or not subject.strip():
        return "Validation error: Subject cannot be empty."
    if not body or not body.strip():
        return "Validation error: Email body cannot be empty."

    confirmed = confirmed and consume_tool_authorization("send_email")
    if not confirmed:
        return (
            "⚠️ CONFIRMATION REQUIRED BEFORE SENDING:\n"
            f"Recipient: {valid_to}\n"
            f"Subject:   {subject.strip()}\n"
            "Body:\n"
            f"----------------------------------------\n"
            f"{body.strip()}\n"
            f"----------------------------------------\n"
            "This email has NOT been sent yet.\n"
            "Ask user: 'Are you sure you want to send this email? (yes/no)'"
        )

    try:
        sent = gmail_service.send_email(to=valid_to, subject=subject.strip(), body=body.strip())
        return (
            f"Email sent successfully!\n"
            f"Message ID: {sent['id']}\n"
            f"To:         {sent['to']}\n"
            f"Subject:    {sent['subject']}\n"
            f"Status:     Delivered to Gmail outgoing queue."
        )
    except (ValueError, RuntimeError) as err:
        return f"Failed to send email: {err}"


# ── 6. Reply to Email (With Safeguard) ────────────────────────────────────────

@tool
def reply_to_email(
    message_id: str,
    body: str,
    reply_all: bool = False,
    confirmed: bool = False,
) -> str:
    """Reply to an email preserving thread. Set confirmed=True ONLY after explicit user confirmation."""
    clean_id = str(message_id).strip()
    if not clean_id:
        return "Error: message_id cannot be empty."
    if not body or not body.strip():
        return "Error: Reply body cannot be empty."

    try:
        orig = gmail_service.get_message_detail(clean_id)
    except Exception as err:
        return f"Error retrieving original message '{clean_id}': {err}"

    orig_sender = orig.get("sender", "Unknown sender")
    orig_subject = orig.get("subject", "(No subject)")
    reply_subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"

    confirmed = confirmed and consume_tool_authorization("reply_to_email")
    if not confirmed:
        return (
            "⚠️ CONFIRMATION REQUIRED BEFORE SENDING REPLY:\n"
            f"Replying to Message ID: {clean_id}\n"
            f"Original Subject:       {orig_subject}\n"
            f"Recipient:              {orig_sender}\n"
            f"Reply Subject:          {reply_subject}\n"
            f"Reply All:              {reply_all}\n"
            "Proposed Reply Body:\n"
            f"----------------------------------------\n"
            f"{body.strip()}\n"
            f"----------------------------------------\n"
            "This reply has NOT been sent yet.\n"
            "Ask user: 'Do you want to send this reply? (yes/no)'"
        )

    try:
        sent = gmail_service.reply_to_message(
            message_id=clean_id,
            body=body.strip(),
            reply_all=reply_all,
        )
        return (
            f"Reply sent successfully!\n"
            f"Message ID: {sent['id']}\n"
            f"Thread ID:  {sent['thread_id']}\n"
            f"To:         {sent['to']}\n"
            f"Subject:    {sent['subject']}\n"
            f"Status:     Reply delivered in the same thread."
        )
    except Exception as err:
        return f"Failed to send reply: {err}"


# ── 7. Mark as Read ───────────────────────────────────────────────────────────

@tool
def mark_as_read(message_ids: Union[list[str], str]) -> str:
    """Mark one or more email IDs as read by removing the UNREAD label."""
    id_list = _normalize_id_list(message_ids)
    if not id_list:
        return "Error: No message IDs provided."

    try:
        count = gmail_service.modify_message_labels(
            message_ids=id_list,
            remove_labels=["UNREAD"],
        )
        return f"Successfully marked {count} email(s) as read."
    except (ValueError, RuntimeError) as err:
        return f"Failed to mark emails as read: {err}"


# ── 8. Mark as Unread ─────────────────────────────────────────────────────────

@tool
def mark_as_unread(message_ids: Union[list[str], str]) -> str:
    """Mark one or more email IDs as unread by adding the UNREAD label."""
    id_list = _normalize_id_list(message_ids)
    if not id_list:
        return "Error: No message IDs provided."

    try:
        count = gmail_service.modify_message_labels(
            message_ids=id_list,
            add_labels=["UNREAD"],
        )
        return f"Successfully marked {count} email(s) as unread."
    except (ValueError, RuntimeError) as err:
        return f"Failed to mark emails as unread: {err}"


# ── 9. Archive Messages ───────────────────────────────────────────────────────

@tool
def archive_messages(
    message_ids: Union[list[str], str],
    confirmed: bool = True,
) -> str:
    """Archive one or more email IDs by removing them from the INBOX."""
    id_list = _normalize_id_list(message_ids)
    if not id_list:
        return "Error: No message IDs provided."

    if len(id_list) > 5:
        confirmed = confirmed and consume_tool_authorization("archive_messages")
    if len(id_list) > 5 and not confirmed:
        return (
            f"⚠️ CONFIRMATION REQUIRED FOR BULK ARCHIVE:\n"
            f"You requested to archive {len(id_list)} messages.\n"
            "Please confirm if you want to archive these messages (yes/no)."
        )

    try:
        count = gmail_service.modify_message_labels(
            message_ids=id_list,
            remove_labels=["INBOX"],
        )
        return f"Successfully archived {count} email(s) from your inbox."
    except (ValueError, RuntimeError) as err:
        return f"Failed to archive emails: {err}"


# ── 10. Trash Messages (With Safeguard) ────────────────────────────────────────

@tool
def trash_messages(
    message_ids: Union[list[str], str],
    confirmed: bool = False,
) -> str:
    """Move one or more email IDs to Gmail Trash. Set confirmed=True ONLY after user confirmation."""
    id_list = _normalize_id_list(message_ids)
    if not id_list:
        return "Error: No message IDs provided."

    if len(id_list) > 10:
        return f"Error: Cannot trash {len(id_list)} messages at once. Maximum limit is 10."

    confirmed = confirmed and consume_tool_authorization("trash_messages")
    if not confirmed:
        return (
            "⚠️ CONFIRMATION REQUIRED BEFORE TRASHING:\n"
            f"Action: Move {len(id_list)} message(s) to Gmail Trash (Message IDs: {', '.join(id_list)})\n"
            "Messages remain in Trash for 30 days. Ask user: 'Are you sure you want to move these to Trash? (yes/no)'"
        )

    try:
        count = gmail_service.trash_messages(id_list)
        return f"Successfully moved {count} email(s) to Gmail Trash."
    except (ValueError, RuntimeError) as err:
        return f"Failed to trash messages: {err}"


# ── 11. Create Label ──────────────────────────────────────────────────────────

@tool
def create_label(label_name: str) -> str:
    """Create a custom Gmail label if it does not already exist."""
    clean_name = str(label_name).strip()
    if not clean_name:
        return "Error: label_name cannot be empty."

    try:
        label_id = gmail_service.get_or_create_label(clean_name)
        return f"Label '{clean_name}' is ready (Label ID: {label_id})."
    except (ValueError, RuntimeError) as err:
        return f"Failed to create label: {err}"


# ── 12. Apply Label ───────────────────────────────────────────────────────────

@tool
def apply_label(message_ids: Union[list[str], str], label_name: str) -> str:
    """Apply a Gmail label to one or more email IDs."""
    id_list = _normalize_id_list(message_ids)
    if not id_list:
        return "Error: No message IDs provided."
    if not label_name or not str(label_name).strip():
        return "Error: label_name cannot be empty."

    try:
        label_id = gmail_service.get_or_create_label(str(label_name).strip())
        count = gmail_service.modify_message_labels(
            message_ids=id_list,
            add_labels=[label_id],
        )
        return f"Successfully applied label '{label_name}' to {count} message(s)."
    except (ValueError, RuntimeError) as err:
        return f"Failed to apply label: {err}"
