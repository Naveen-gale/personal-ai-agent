"""
tests/test_imports.py
----------------------
Verifies that all project modules and tools import cleanly without errors.

Run with:
    .\\agent\\.venv\\Scripts\\python.exe -m pytest agent\\tests\\test_imports.py -v
"""

import importlib
import pytest


# List every module in the agent package
MODULES_TO_CHECK = [
    "agent",
    "agent.state",
    "agent.auth.gmail_auth",
    "agent.services.contacts_service",
    "agent.services.gmail_service",
    "agent.services.date_utils",
    "agent.services.calendar_service",
    "agent.services.tasks_service",
    "agent.services.notification_service",
    "agent.services.reminder_service",
    "agent.services.reminder_worker",
    "agent.tools.contacts_tools",
    "agent.tools.assistant_tools",
    "agent.tools.gmail_tools",
    "agent.tools.calendar_tools",
    "agent.tools.tasks_tools",
    "agent.tools.reminder_tools",
    "agent.nodes.assistant_node",
    "agent.graph",
    "agent.main",
]

# List of all tools that must be registered and invocable
TOOLS_TO_CHECK = [
    # Gmail Tools
    ("agent.tools.gmail_tools", "search_gmail"),
    ("agent.tools.gmail_tools", "read_email"),
    ("agent.tools.gmail_tools", "get_unread_emails"),
    ("agent.tools.gmail_tools", "create_draft"),
    ("agent.tools.gmail_tools", "send_email"),
    ("agent.tools.gmail_tools", "reply_to_email"),
    ("agent.tools.gmail_tools", "mark_as_read"),
    ("agent.tools.gmail_tools", "mark_as_unread"),
    ("agent.tools.gmail_tools", "archive_messages"),
    ("agent.tools.gmail_tools", "trash_messages"),
    ("agent.tools.gmail_tools", "create_label"),
    ("agent.tools.gmail_tools", "apply_label"),
    # General Tools
    ("agent.tools.assistant_tools", "get_current_datetime"),
    # Contacts Tools
    ("agent.tools.contacts_tools", "find_contact"),
    ("agent.tools.contacts_tools", "create_contact"),
    # Calendar Tools
    ("agent.tools.calendar_tools", "get_today_events"),
    ("agent.tools.calendar_tools", "list_calendar_events"),
    ("agent.tools.calendar_tools", "search_calendar_events"),
    ("agent.tools.calendar_tools", "create_calendar_event"),
    ("agent.tools.calendar_tools", "update_calendar_event"),
    ("agent.tools.calendar_tools", "delete_calendar_event"),
    # Tasks Tools
    ("agent.tools.tasks_tools", "list_pending_tasks"),
    ("agent.tools.tasks_tools", "list_completed_tasks"),
    ("agent.tools.tasks_tools", "create_task"),
    ("agent.tools.tasks_tools", "update_task"),
    ("agent.tools.tasks_tools", "complete_task"),
    ("agent.tools.tasks_tools", "delete_task"),
    # Reminder Tools
    ("agent.tools.reminder_tools", "create_reminder"),
    ("agent.tools.reminder_tools", "list_reminders"),
    ("agent.tools.reminder_tools", "cancel_reminder"),
]


@pytest.mark.parametrize("module_name", MODULES_TO_CHECK)
def test_module_imports(module_name):
    """Each module must import cleanly without syntax or import errors."""
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        pytest.fail(f"Failed to import '{module_name}': {type(exc).__name__}: {exc}")


@pytest.mark.parametrize("module_path, tool_name", TOOLS_TO_CHECK)
def test_tool_is_invocable(module_path, tool_name):
    """Each tool must be an invocable LangChain StructuredTool with .name and .invoke()."""
    mod = importlib.import_module(module_path)
    tool_obj = getattr(mod, tool_name, None)

    assert tool_obj is not None, f"Tool '{tool_name}' not found in '{module_path}'"
    assert hasattr(tool_obj, "name"), f"Tool '{tool_name}' must have a .name attribute"
    assert hasattr(tool_obj, "invoke"), f"Tool '{tool_name}' must have an .invoke() method"
    assert tool_obj.name == tool_name
