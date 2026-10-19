"""
tools/tasks_tools.py
--------------------
LangChain tools for Google Tasks.
Docstrings are concise to maintain low token usage.
"""

from typing import Any
from langchain_core.tools import tool
from agent.tools.confirmation import consume_tool_authorization

from agent.services.tasks_service import (
    complete_task as complete_task_service,
    create_task as create_task_service,
    delete_task as delete_task_service,
    list_completed_tasks as list_completed_tasks_service,
    list_pending_tasks as list_pending_tasks_service,
    update_task as update_task_service,
)


@tool
def list_pending_tasks(task_list_id: str = "@default", max_results: int = 20) -> dict:
    """List pending (uncompleted) tasks from Google Tasks."""
    try:
        return list_pending_tasks_service(task_list_id=task_list_id, max_results=max_results)
    except Exception as error:
        return {"success": False, "tasks": [], "count": 0, "message": f"Failed to list tasks: {error}"}


@tool
def list_completed_tasks(task_list_id: str = "@default", max_results: int = 20) -> dict:
    """List completed tasks from Google Tasks."""
    try:
        return list_completed_tasks_service(task_list_id=task_list_id, max_results=max_results)
    except Exception as error:
        return {"success": False, "tasks": [], "count": 0, "message": f"Failed to list completed tasks: {error}"}


@tool
def create_task(
    title: str,
    notes: str = "",
    due_date: str = "",
    task_list_id: str = "@default",
    confirmed: bool = False,
) -> dict:
    """Preview task when confirmed=False; add to Google Tasks only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("create_task")
        return create_task_service(
            title=title,
            notes=notes,
            due_date=due_date or None,
            task_list_id=task_list_id,
            confirmed=confirmed,
        )
    except Exception as error:
        return {
            "success": False,
            "created": False,
            "requires_confirmation": False,
            "message": f"Could not create task: {error}",
        }


@tool
def update_task(
    task_id: str,
    title: str = "",
    notes: str = "",
    due_date: str = "",
    task_list_id: str = "@default",
    confirmed: bool = False,
) -> dict:
    """Preview task changes when confirmed=False; update only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("update_task")
        return update_task_service(
            task_id=task_id,
            title=title or None,
            notes=notes or None,
            due_date=due_date if due_date != "" else None,
            task_list_id=task_list_id,
            confirmed=confirmed,
        )
    except Exception as error:
        return {
            "success": False,
            "updated": False,
            "requires_confirmation": False,
            "message": f"Could not update task: {error}",
        }


@tool
def complete_task(
    task_id: str,
    task_list_id: str = "@default",
    confirmed: bool = False,
) -> dict:
    """Preview completing task when confirmed=False; mark complete only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("complete_task")
        return complete_task_service(
            task_id=task_id,
            task_list_id=task_list_id,
            confirmed=confirmed,
        )
    except Exception as error:
        return {
            "success": False,
            "completed": False,
            "requires_confirmation": False,
            "message": f"Could not complete task: {error}",
        }


@tool
def delete_task(
    task_id: str,
    task_list_id: str = "@default",
    confirmed: bool = False,
) -> dict:
    """Preview task deletion when confirmed=False; delete permanently only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("delete_task")
        return delete_task_service(
            task_id=task_id,
            task_list_id=task_list_id,
            confirmed=confirmed,
        )
    except Exception as error:
        return {
            "success": False,
            "deleted": False,
            "requires_confirmation": False,
            "message": f"Could not delete task: {error}",
        }


TASKS_TOOLS = [
    list_pending_tasks,
    list_completed_tasks,
    create_task,
    update_task,
    complete_task,
    delete_task,
]
