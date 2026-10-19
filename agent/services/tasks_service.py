"""
services/tasks_service.py
-------------------------
Google Tasks API v1 service layer.

Responsibilities:
  - Authenticate with Google Tasks using shared OAuth credentials.
  - List task lists and filter pending vs completed tasks.
  - Create tasks with optional notes and due dates.
    IMPORTANT: Google Tasks due dates have date-level semantics (RFC 3339 timestamp
    with 00:00:00.000Z). Google Tasks does not provide a clock-time alarm engine;
    use the reminder engine for specific-minute notifications!
  - Update, complete, and delete tasks with confirmation safeguards.
  - Return clean, structured dictionaries.
"""

from collections.abc import Mapping
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.auth.gmail_auth import TASKS_SCOPES, get_credentials
from agent.services.date_utils import (
    DEFAULT_TIMEZONE_NAME,
    format_local_datetime,
    parse_date_only_due,
    parse_datetime,
)


def get_tasks_service() -> Any:
    """Build the Google Tasks API v1 client using OAuth credentials."""
    credentials = get_credentials(required_scopes=TASKS_SCOPES)
    return build("tasks", "v1", credentials=credentials, cache_discovery=False)


def _execute(request: Any) -> dict[str, Any]:
    """Execute a Google Tasks API request with error handling."""
    try:
        response = request.execute()
    except HttpError as error:
        status = getattr(error.resp, "status", "unknown")
        if status == 404:
            raise RuntimeError("Task or task list not found (404).") from error
        raise RuntimeError(
            f"Google Tasks API request failed (HTTP {status}). "
            "Check that the Google Tasks API is enabled and your OAuth token has the tasks scope."
        ) from error
    except Exception as error:
        raise RuntimeError(
            f"Google Tasks API request failed ({type(error).__name__}). "
            "Check network connectivity and credentials."
        ) from error

    if not isinstance(response, Mapping):
        raise RuntimeError("Google Tasks API returned an invalid response.")
    return dict(response)


def _format_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Convert raw Tasks API task item into a clean, structured dictionary."""
    due_raw = task.get("due", "")
    due_display = ""
    if due_raw:
        try:
            dt = parse_datetime(due_raw)
            due_display = dt.strftime("%A, %B %d, %Y (Date only)")
        except Exception:
            due_display = due_raw

    return {
        "id": task.get("id", ""),
        "title": task.get("title", "(Untitled Task)"),
        "notes": task.get("notes", ""),
        "status": task.get("status", "needsAction"),  # "needsAction" or "completed"
        "is_completed": task.get("status") == "completed",
        "due": due_raw,
        "due_display": due_display,
        "updated": task.get("updated", ""),
        "completed_at": task.get("completed", ""),
    }


def list_task_lists(max_results: int = 20) -> dict[str, Any]:
    """Retrieve all Google Tasks lists for the user."""
    service = get_tasks_service()
    response = _execute(
        service.tasklists().list(maxResults=min(max(1, max_results), 100))
    )
    raw_lists = response.get("items", [])
    task_lists = [
        {"id": item.get("id"), "title": item.get("title", "My Tasks")}
        for item in raw_lists
    ]
    return {
        "success": True,
        "task_lists": task_lists,
        "count": len(task_lists),
    }


def list_pending_tasks(
    task_list_id: str = "@default", max_results: int = 20
) -> dict[str, Any]:
    """
    List pending (uncompleted) tasks.
    """
    service = get_tasks_service()
    response = _execute(
        service.tasks().list(
            tasklist=task_list_id,
            showCompleted=False,
            showHidden=False,
            maxResults=min(max(1, max_results), 100),
        )
    )
    raw_items = response.get("items", [])
    tasks = [_format_task(item) for item in raw_items if item.get("status") != "completed"]

    return {
        "success": True,
        "tasks": tasks,
        "count": len(tasks),
        "task_list_id": task_list_id,
        "note": "Google Tasks due dates indicate calendar days, not specific-minute alarms.",
    }


def list_completed_tasks(
    task_list_id: str = "@default", max_results: int = 20
) -> dict[str, Any]:
    """
    List completed tasks from a task list.
    """
    service = get_tasks_service()
    response = _execute(
        service.tasks().list(
            tasklist=task_list_id,
            showCompleted=True,
            showHidden=True,
            maxResults=min(max(1, max_results), 100),
        )
    )
    raw_items = response.get("items", [])
    tasks = [_format_task(item) for item in raw_items if item.get("status") == "completed"]

    return {
        "success": True,
        "tasks": tasks,
        "count": len(tasks),
        "task_list_id": task_list_id,
    }


def create_task(
    title: str,
    notes: str = "",
    due_date: str | None = None,
    task_list_id: str = "@default",
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Create a new task in Google Tasks.
    Requires explicit confirmation: previews the task before creation.
    """
    t_clean = (title or "").strip()
    if not t_clean:
        raise ValueError("Task title is required.")

    due_rfc = None
    due_display = "No due date"
    if due_date and due_date.strip():
        due_rfc = parse_date_only_due(due_date.strip())
        due_display = due_rfc[:10]

    preview = {
        "title": t_clean,
        "notes": notes.strip(),
        "due_date": due_display,
        "task_list_id": task_list_id,
    }

    if not confirmed:
        return {
            "success": True,
            "created": False,
            "requires_confirmation": True,
            "preview": preview,
            "message": (
                f"Please confirm: Add task '{t_clean}' (Due: {due_display}) to your Tasks list? "
                f"(Type 'yes' to proceed)"
            ),
        }

    task_body: dict[str, Any] = {"title": t_clean}
    if notes.strip():
        task_body["notes"] = notes.strip()
    if due_rfc:
        task_body["due"] = due_rfc

    service = get_tasks_service()
    created = _execute(service.tasks().insert(tasklist=task_list_id, body=task_body))
    formatted = _format_task(created)

    return {
        "success": True,
        "created": True,
        "requires_confirmation": False,
        "task": formatted,
        "message": f"Task '{t_clean}' added to your task list successfully.",
    }


def update_task(
    task_id: str,
    title: str | None = None,
    notes: str | None = None,
    due_date: str | None = None,
    task_list_id: str = "@default",
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Update an existing task's title, notes, or due date.
    Previews changes and requires confirmation.
    """
    tid = (task_id or "").strip()
    if not tid:
        raise ValueError("Task ID is required.")

    service = get_tasks_service()
    existing_raw = _execute(service.tasks().get(tasklist=task_list_id, task=tid))
    existing = _format_task(existing_raw)

    patch_body: dict[str, Any] = {}
    preview_changes: dict[str, Any] = {"id": tid, "current_title": existing["title"]}

    if title is not None and title.strip():
        patch_body["title"] = title.strip()
        preview_changes["new_title"] = title.strip()

    if notes is not None:
        patch_body["notes"] = notes.strip()
        preview_changes["new_notes"] = notes.strip()

    if due_date is not None:
        if due_date.strip():
            rfc = parse_date_only_due(due_date.strip())
            patch_body["due"] = rfc
            preview_changes["new_due"] = rfc[:10]
        else:
            patch_body["due"] = None
            preview_changes["new_due"] = "Cleared"

    if not patch_body:
        return {"success": True, "updated": False, "message": "No changes specified."}

    if not confirmed:
        return {
            "success": True,
            "updated": False,
            "requires_confirmation": True,
            "preview": preview_changes,
            "message": (
                f"Please confirm: Update task '{existing['title']}' with these changes? "
                f"(Type 'yes' to proceed)"
            ),
        }

    updated = _execute(
        service.tasks().patch(tasklist=task_list_id, task=tid, body=patch_body)
    )
    formatted = _format_task(updated)

    return {
        "success": True,
        "updated": True,
        "requires_confirmation": False,
        "task": formatted,
        "message": f"Task '{formatted['title']}' updated successfully.",
    }


def complete_task(
    task_id: str,
    task_list_id: str = "@default",
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Mark a task as completed.
    Requires confirmation before marking complete.
    """
    tid = (task_id or "").strip()
    if not tid:
        raise ValueError("Task ID is required.")

    service = get_tasks_service()
    existing_raw = _execute(service.tasks().get(tasklist=task_list_id, task=tid))
    existing = _format_task(existing_raw)

    if not confirmed:
        return {
            "success": True,
            "completed": False,
            "requires_confirmation": True,
            "preview": {"id": tid, "title": existing["title"]},
            "message": f"Please confirm: Mark task '{existing['title']}' as completed? (Type 'yes' to proceed)",
        }

    patch_body = {"status": "completed"}
    updated = _execute(
        service.tasks().patch(tasklist=task_list_id, task=tid, body=patch_body)
    )
    formatted = _format_task(updated)

    return {
        "success": True,
        "completed": True,
        "requires_confirmation": False,
        "task": formatted,
        "message": f"Task '{formatted['title']}' marked as complete.",
    }


def delete_task(
    task_id: str,
    task_list_id: str = "@default",
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Delete a task from Google Tasks.
    Requires explicit user confirmation before deletion.
    """
    tid = (task_id or "").strip()
    if not tid:
        raise ValueError("Task ID is required.")

    service = get_tasks_service()
    existing_raw = _execute(service.tasks().get(tasklist=task_list_id, task=tid))
    existing = _format_task(existing_raw)

    if not confirmed:
        return {
            "success": True,
            "deleted": False,
            "requires_confirmation": True,
            "preview": {"id": tid, "title": existing["title"]},
            "message": (
                f"Please confirm: Delete task '{existing['title']}' permanently from Google Tasks? "
                f"(Type 'yes' to proceed)"
            ),
        }

    try:
        service.tasks().delete(tasklist=task_list_id, task=tid).execute()
    except Exception as error:
        raise RuntimeError(f"Failed to delete task ({type(error).__name__}).") from error

    return {
        "success": True,
        "deleted": True,
        "requires_confirmation": False,
        "message": f"Task '{existing['title']}' deleted successfully.",
    }

