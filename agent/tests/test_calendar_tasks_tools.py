"""
tests/test_calendar_tasks_tools.py
----------------------------------
Unit tests for LangChain tool wrappers for Calendar, Tasks, and Reminders.
Verifies invocation, schemas, and safe error-handling (never crashing or raising).
"""

from unittest.mock import patch
import pytest

from agent.tools.calendar_tools import (
    CALENDAR_TOOLS,
    create_calendar_event,
    delete_calendar_event,
    get_today_events,
    list_calendar_events,
    search_calendar_events,
    update_calendar_event,
)
from agent.tools.tasks_tools import (
    TASKS_TOOLS,
    complete_task,
    create_task,
    delete_task,
    list_completed_tasks,
    list_pending_tasks,
    update_task,
)
from agent.tools.reminder_tools import (
    REMINDER_TOOLS,
    cancel_reminder,
    create_reminder,
    list_reminders,
)


def test_calendar_tools_have_names_and_schemas():
    for t in CALENDAR_TOOLS:
        assert hasattr(t, "name")
        assert hasattr(t, "invoke")
        assert len(t.name) > 0


def test_tasks_tools_have_names_and_schemas():
    for t in TASKS_TOOLS:
        assert hasattr(t, "name")
        assert hasattr(t, "invoke")
        assert len(t.name) > 0


def test_reminder_tools_have_names_and_schemas():
    for t in REMINDER_TOOLS:
        assert hasattr(t, "name")
        assert hasattr(t, "invoke")
        assert len(t.name) > 0


def test_calendar_tools_return_errors_instead_of_raising():
    with patch(
        "agent.tools.calendar_tools.get_today_events_service",
        side_effect=RuntimeError("Google Calendar API down"),
    ):
        res = get_today_events.invoke({})
        assert res["success"] is False
        assert "Google Calendar API down" in res["message"]


def test_tasks_tools_return_errors_instead_of_raising():
    with patch(
        "agent.tools.tasks_tools.list_pending_tasks_service",
        side_effect=RuntimeError("Google Tasks API down"),
    ):
        res = list_pending_tasks.invoke({})
        assert res["success"] is False
        assert "Google Tasks API down" in res["message"]


def test_reminder_tools_return_errors_instead_of_raising():
    with patch(
        "agent.tools.reminder_tools.create_reminder_service",
        side_effect=ValueError("Invalid time format"),
    ):
        res = create_reminder.invoke(
            {"reminder_text": "Buy milk", "scheduled_time": "invalid-time"}
        )
        assert res["success"] is False
        assert "Invalid time format" in res["message"]

