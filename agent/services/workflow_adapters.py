"""
services/workflow_adapters.py
-----------------------------
Tool adapter layer and registry for the Workflow Automation Engine.

Responsibilities:
  - Whitelist allowed workflow tools and declare their parameter schemas.
  - Wrap existing agent tools to ensure predictable input/output contracts.
  - Enforce human approval requirements on sensitive/destructive operations.
  - Provide an LLM synthesis tool for summarization, planning, and task extraction.
"""

from typing import Any, Callable
import json

from agent.tools.assistant_tools import get_current_datetime
from agent.tools.calendar_tools import (
    create_calendar_event,
    delete_calendar_event,
    get_today_events,
    list_calendar_events,
    search_calendar_events,
    update_calendar_event,
)
from agent.tools.contacts_tools import create_contact, find_contact
from agent.tools.gmail_tools import (
    create_draft,
    get_unread_emails,
    read_email,
    search_gmail,
    send_email,
)
from agent.tools.reminder_tools import cancel_reminder, create_reminder, list_reminders
from agent.tools.tasks_tools import (
    complete_task,
    create_task,
    delete_task,
    list_completed_tasks,
    list_pending_tasks,
    update_task,
)
from agent.nodes.assistant_node import get_base_llm
from langchain_core.messages import HumanMessage, SystemMessage


# Tool metadata schema: name, description, category, requires_approval, handler
WORKFLOW_TOOL_REGISTRY: dict[str, dict[str, Any]] = {}


def register_tool(
    name: str,
    description: str,
    category: str,
    parameters: dict[str, Any],
    requires_approval: bool = False,
    is_destructive: bool = False,
):
    """Decorator to register an allowed workflow tool."""

    def decorator(fn: Callable[..., Any]):
        WORKFLOW_TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "category": category,
            "parameters": parameters,
            "requires_approval": requires_approval,
            "is_destructive": is_destructive,
            "handler": fn,
        }
        return fn

    return decorator


# ── Email Tools ───────────────────────────────────────────────────────────────

@register_tool(
    name="get_unread_emails",
    description="Retrieve and summarize unread emails from Gmail.",
    category="email",
    parameters={"max_results": {"type": "integer", "default": 5, "description": "Max unread emails to inspect"}},
)
def _tool_get_unread_emails(max_results: int = 5) -> dict[str, Any]:
    res = get_unread_emails.invoke({"max_results": int(max_results)})
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="search_gmail",
    description="Search Gmail messages using natural query or Gmail syntax.",
    category="email",
    parameters={
        "query": {"type": "string", "required": True, "description": "Search query"},
        "max_results": {"type": "integer", "default": 5, "description": "Max results to return"},
    },
)
def _tool_search_gmail(query: str, max_results: int = 5) -> dict[str, Any]:
    res = search_gmail.invoke({"query": str(query), "max_results": int(max_results)})
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="create_draft",
    description="Prepare an email draft in Gmail without sending it.",
    category="email",
    parameters={
        "recipient": {"type": "string", "required": True, "description": "Recipient email address"},
        "subject": {"type": "string", "required": True, "description": "Email subject"},
        "body": {"type": "string", "required": True, "description": "Email body content"},
    },
)
def _tool_create_draft(recipient: str, subject: str, body: str) -> dict[str, Any]:
    res = create_draft.invoke({"recipient": recipient, "subject": subject, "body": body})
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="send_email",
    description="Send an email to a recipient. Requires user approval by default.",
    category="email",
    parameters={
        "recipient": {"type": "string", "required": True, "description": "Recipient email address"},
        "subject": {"type": "string", "required": True, "description": "Email subject"},
        "body": {"type": "string", "required": True, "description": "Email body content"},
    },
    requires_approval=True,
    is_destructive=True,
)
def _tool_send_email(recipient: str, subject: str, body: str, confirmed: bool = True) -> dict[str, Any]:
    res = send_email.invoke({"recipient": recipient, "subject": subject, "body": body, "confirmed": confirmed})
    return res if isinstance(res, dict) else {"result": res}


# ── Calendar Tools ────────────────────────────────────────────────────────────

@register_tool(
    name="get_today_events",
    description="Retrieve all Google Calendar events scheduled for today.",
    category="calendar",
    parameters={"time_zone": {"type": "string", "default": "Asia/Kolkata", "description": "User time zone"}},
)
def _tool_get_today_events(time_zone: str = "Asia/Kolkata") -> dict[str, Any]:
    res = get_today_events.invoke({"time_zone": time_zone})
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="list_calendar_events",
    description="List calendar events within an optional time range.",
    category="calendar",
    parameters={
        "start_time": {"type": "string", "default": "", "description": "Start datetime or 'tomorrow'"},
        "end_time": {"type": "string", "default": "", "description": "End datetime"},
        "max_results": {"type": "integer", "default": 10, "description": "Max events to return"},
        "time_zone": {"type": "string", "default": "Asia/Kolkata", "description": "Time zone"},
    },
)
def _tool_list_calendar_events(
    start_time: str = "", end_time: str = "", max_results: int = 10, time_zone: str = "Asia/Kolkata"
) -> dict[str, Any]:
    res = list_calendar_events.invoke(
        {"start_time": start_time, "end_time": end_time, "max_results": int(max_results), "time_zone": time_zone}
    )
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="create_calendar_event",
    description="Create a new calendar event. Requires user approval by default.",
    category="calendar",
    parameters={
        "title": {"type": "string", "required": True, "description": "Event title/summary"},
        "start_time": {"type": "string", "required": True, "description": "Start datetime"},
        "end_time": {"type": "string", "default": "", "description": "End datetime"},
        "duration_minutes": {"type": "integer", "default": 30, "description": "Duration in minutes"},
        "description": {"type": "string", "default": "", "description": "Event description"},
        "location": {"type": "string", "default": "", "description": "Event location"},
        "time_zone": {"type": "string", "default": "Asia/Kolkata", "description": "Time zone"},
    },
    requires_approval=True,
)
def _tool_create_calendar_event(
    title: str,
    start_time: str,
    end_time: str = "",
    duration_minutes: int = 30,
    description: str = "",
    location: str = "",
    time_zone: str = "Asia/Kolkata",
    confirmed: bool = True,
) -> dict[str, Any]:
    res = create_calendar_event.invoke(
        {
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "duration_minutes": int(duration_minutes),
            "description": description,
            "location": location,
            "time_zone": time_zone,
            "confirmed": confirmed,
        }
    )
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="delete_calendar_event",
    description="Delete/cancel a calendar event. Requires user approval.",
    category="calendar",
    parameters={"event_id": {"type": "string", "required": True, "description": "Event ID to delete"}},
    requires_approval=True,
    is_destructive=True,
)
def _tool_delete_calendar_event(event_id: str, confirmed: bool = True) -> dict[str, Any]:
    res = delete_calendar_event.invoke({"event_id": event_id, "confirmed": confirmed})
    return res if isinstance(res, dict) else {"result": res}


# ── Tasks Tools ───────────────────────────────────────────────────────────────

@register_tool(
    name="list_pending_tasks",
    description="Retrieve all pending tasks from Google Tasks.",
    category="tasks",
    parameters={
        "task_list_id": {"type": "string", "default": "@default", "description": "Task list ID"},
        "max_results": {"type": "integer", "default": 20, "description": "Max tasks to return"},
    },
)
def _tool_list_pending_tasks(task_list_id: str = "@default", max_results: int = 20) -> dict[str, Any]:
    res = list_pending_tasks.invoke({"task_list_id": task_list_id, "max_results": int(max_results)})
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="create_task",
    description="Create a task in Google Tasks with optional notes and due date.",
    category="tasks",
    parameters={
        "title": {"type": "string", "required": True, "description": "Task title"},
        "notes": {"type": "string", "default": "", "description": "Optional task notes"},
        "due_date": {"type": "string", "default": "", "description": "Optional due date"},
    },
    requires_approval=False,
)
def _tool_create_task(title: str, notes: str = "", due_date: str = "", confirmed: bool = True) -> dict[str, Any]:
    res = create_task.invoke({"title": title, "notes": notes, "due_date": due_date, "confirmed": confirmed})
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="complete_task",
    description="Mark a task as completed.",
    category="tasks",
    parameters={"task_id": {"type": "string", "required": True, "description": "Task ID to complete"}},
    requires_approval=False,
)
def _tool_complete_task(task_id: str, confirmed: bool = True) -> dict[str, Any]:
    res = complete_task.invoke({"task_id": task_id, "confirmed": confirmed})
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="delete_task",
    description="Delete a task from Google Tasks. Requires user approval.",
    category="tasks",
    parameters={"task_id": {"type": "string", "required": True, "description": "Task ID to delete"}},
    requires_approval=True,
    is_destructive=True,
)
def _tool_delete_task(task_id: str, confirmed: bool = True) -> dict[str, Any]:
    res = delete_task.invoke({"task_id": task_id, "confirmed": confirmed})
    return res if isinstance(res, dict) else {"result": res}


# ── Reminders Tools ───────────────────────────────────────────────────────────

@register_tool(
    name="list_reminders",
    description="Retrieve scheduled reminders from persistent storage.",
    category="reminders",
    parameters={
        "status": {"type": "string", "default": "pending", "description": "Status filter (pending, all, etc.)"},
        "limit": {"type": "integer", "default": 20, "description": "Max reminders to return"},
    },
)
def _tool_list_reminders(status: str = "pending", limit: int = 20) -> dict[str, Any]:
    res = list_reminders.invoke({"status": status, "limit": int(limit)})
    return res if isinstance(res, dict) else {"result": res}


@register_tool(
    name="create_reminder",
    description="Create a scheduled reminder for a specific date and time.",
    category="reminders",
    parameters={
        "reminder_text": {"type": "string", "required": True, "description": "Reminder text"},
        "scheduled_time": {"type": "string", "required": True, "description": "When to alert (e.g. 'tomorrow at 7 PM')"},
        "recurrence_rule": {"type": "string", "default": "", "description": "Optional recurrence (e.g. 'daily')"},
    },
    requires_approval=False,
)
def _tool_create_reminder(
    reminder_text: str, scheduled_time: str, recurrence_rule: str = "", confirmed: bool = True
) -> dict[str, Any]:
    res = create_reminder.invoke(
        {"reminder_text": reminder_text, "scheduled_time": scheduled_time, "recurrence_rule": recurrence_rule, "confirmed": confirmed}
    )
    return res if isinstance(res, dict) else {"result": res}


# ── LLM Synthesis Tool ────────────────────────────────────────────────────────

@register_tool(
    name="llm_synthesize",
    description="Use AI to synthesize, format, summarize, or extract actionable items from prior step outputs.",
    category="ai",
    parameters={
        "prompt": {"type": "string", "required": True, "description": "Instructions for synthesis"},
        "context_data": {"type": "any", "required": False, "description": "Data from prior steps to analyze"},
    },
    requires_approval=False,
)
def _tool_llm_synthesize(prompt: str, context_data: Any = None) -> dict[str, Any]:
    """Invoke Groq LLM to synthesize data from workflow steps."""
    llm = get_base_llm()
    data_str = json.dumps(context_data, ensure_ascii=False, indent=2, default=str) if context_data is not None else ""
    user_content = f"{prompt}\n\nContext Data:\n{data_str}" if data_str else prompt
    sys_msg = SystemMessage(content="You are an expert AI executive assistant. Provide concise, actionable summaries or plans.")
    response = llm.invoke([sys_msg, HumanMessage(content=user_content)])
    content = str(response.content) if hasattr(response, "content") else str(response)
    return {"success": True, "result": content, "summary": content}


def get_available_tools() -> list[dict[str, Any]]:
    """Return public schema for all registered workflow tools."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "category": t["category"],
            "parameters": t["parameters"],
            "requires_approval": t["requires_approval"],
            "is_destructive": t["is_destructive"],
        }
        for t in WORKFLOW_TOOL_REGISTRY.values()
    ]


def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a registered workflow tool by name with arguments."""
    if name not in WORKFLOW_TOOL_REGISTRY:
        raise ValueError(
            f"Tool '{name}' is not allowed in workflows. Available tools: {list(WORKFLOW_TOOL_REGISTRY.keys())}"
        )
    handler = WORKFLOW_TOOL_REGISTRY[name]["handler"]
    return handler(**arguments)
