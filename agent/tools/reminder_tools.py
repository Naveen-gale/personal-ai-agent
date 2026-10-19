"""
tools/reminder_tools.py
-----------------------
LangChain tools for Scheduled Reminders.
Docstrings are concise to maintain low token usage on Groq.
"""

from typing import Any
from langchain_core.tools import tool
from agent.tools.confirmation import consume_tool_authorization

from agent.services.reminder_service import (
    cancel_reminder as cancel_reminder_service,
    create_reminder as create_reminder_service,
    list_reminders as list_reminders_service,
)


@tool
def create_reminder(
    reminder_text: str,
    scheduled_time: str,
    recurrence_rule: str = "",
    delivery_channel: str = "telegram",
    confirmed: bool = False,
) -> dict:
    """Preview reminder when confirmed=False; schedule notification only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("create_reminder")
        return create_reminder_service(
            reminder_text=reminder_text,
            scheduled_time=scheduled_time,
            recurrence_rule=recurrence_rule or None,
            delivery_channel=delivery_channel,
            confirmed=confirmed,
        )
    except Exception as error:
        return {
            "success": False,
            "created": False,
            "requires_confirmation": False,
            "message": f"Could not create reminder: {error}",
        }


@tool
def list_reminders(status: str = "pending", limit: int = 20) -> dict:
    """List scheduled reminders from the database (filter by 'pending', 'delivered', 'cancelled', or 'all')."""
    try:
        return list_reminders_service(status=status, limit=limit)
    except Exception as error:
        return {"success": False, "reminders": [], "count": 0, "message": f"Failed to list reminders: {error}"}


@tool
def cancel_reminder(reminder_id: str, confirmed: bool = False) -> dict:
    """Preview cancellation when confirmed=False; cancel reminder only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("cancel_reminder")
        return cancel_reminder_service(reminder_id=reminder_id, confirmed=confirmed)
    except Exception as error:
        return {
            "success": False,
            "cancelled": False,
            "requires_confirmation": False,
            "message": f"Could not cancel reminder: {error}",
        }


REMINDER_TOOLS = [
    create_reminder,
    list_reminders,
    cancel_reminder,
]
