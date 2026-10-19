"""
tests/test_tasks.py
-------------------
Unit tests for Google Tasks service, operations, and safeguards.
Google Tasks API calls are mocked.
"""

from unittest.mock import MagicMock, patch
import pytest

from agent.auth.gmail_auth import TASKS_SCOPES
from agent.services import tasks_service


def test_tasks_scopes_defined_and_correct():
    assert "https://www.googleapis.com/auth/tasks" in TASKS_SCOPES


def test_get_tasks_service_uses_tasks_scopes():
    mock_creds = MagicMock()
    mock_service = MagicMock()

    with patch(
        "agent.services.tasks_service.get_credentials",
        return_value=mock_creds,
    ) as mock_get_creds, patch(
        "agent.services.tasks_service.build",
        return_value=mock_service,
    ) as mock_build:
        svc = tasks_service.get_tasks_service()

    assert svc is mock_service
    mock_get_creds.assert_called_once_with(required_scopes=TASKS_SCOPES)
    mock_build.assert_called_once_with("tasks", "v1", credentials=mock_creds, cache_discovery=False)


def test_list_pending_tasks_filters_completed():
    mock_service = MagicMock()
    mock_tasks_req = mock_service.tasks.return_value.list.return_value
    mock_tasks_req.execute.return_value = {
        "items": [
            {
                "id": "t-1",
                "title": "Finish Lab Report",
                "status": "needsAction",
                "due": "2026-10-24T00:00:00.000Z",
            },
            {
                "id": "t-2",
                "title": "Completed Exercise",
                "status": "completed",
            },
        ]
    }

    with patch("agent.services.tasks_service.get_tasks_service", return_value=mock_service):
        res = tasks_service.list_pending_tasks()

    assert res["success"] is True
    assert res["count"] == 1
    assert res["tasks"][0]["id"] == "t-1"
    assert res["tasks"][0]["is_completed"] is False
    assert "Date only" in res["tasks"][0]["due_display"]


def test_create_task_safeguard_and_execution():
    mock_service = MagicMock()
    mock_tasks = mock_service.tasks.return_value

    # Preview with confirmed=False
    with patch("agent.services.tasks_service.get_tasks_service", return_value=mock_service):
        res_prev = tasks_service.create_task(
            title="Complete Python Assignment",
            notes="Chapters 4-5",
            due_date="2026-10-25",
            confirmed=False,
        )

    assert res_prev["success"] is True
    assert res_prev["created"] is False
    assert res_prev["requires_confirmation"] is True
    assert res_prev["preview"]["title"] == "Complete Python Assignment"
    mock_tasks.insert.assert_not_called()

    # Confirmed with confirmed=True
    mock_tasks.insert.return_value.execute.return_value = {
        "id": "new-task-1",
        "title": "Complete Python Assignment",
        "status": "needsAction",
        "due": "2026-10-25T00:00:00.000Z",
    }
    with patch("agent.services.tasks_service.get_tasks_service", return_value=mock_service):
        res_conf = tasks_service.create_task(
            title="Complete Python Assignment",
            notes="Chapters 4-5",
            due_date="2026-10-25",
            confirmed=True,
        )

    assert res_conf["success"] is True
    assert res_conf["created"] is True
    assert res_conf["task"]["id"] == "new-task-1"
    mock_tasks.insert.assert_called_once()


def test_create_task_rejects_empty_title():
    with pytest.raises(ValueError, match="Task title is required"):
        tasks_service.create_task(title="", confirmed=False)


def test_complete_task_safeguard_and_execution():
    mock_service = MagicMock()
    mock_tasks = mock_service.tasks.return_value
    mock_tasks.get.return_value.execute.return_value = {
        "id": "t-done",
        "title": "Read Chapter 1",
        "status": "needsAction",
    }

    # Preview
    with patch("agent.services.tasks_service.get_tasks_service", return_value=mock_service):
        res_prev = tasks_service.complete_task(task_id="t-done", confirmed=False)

    assert res_prev["requires_confirmation"] is True
    assert res_prev["completed"] is False
    mock_tasks.patch.assert_not_called()

    # Confirmed
    mock_tasks.patch.return_value.execute.return_value = {
        "id": "t-done",
        "title": "Read Chapter 1",
        "status": "completed",
    }
    with patch("agent.services.tasks_service.get_tasks_service", return_value=mock_service):
        res_conf = tasks_service.complete_task(task_id="t-done", confirmed=True)

    assert res_conf["completed"] is True
    mock_tasks.patch.assert_called_once_with(
        tasklist="@default", task="t-done", body={"status": "completed"}
    )


def test_delete_task_safeguard_and_execution():
    mock_service = MagicMock()
    mock_tasks = mock_service.tasks.return_value
    mock_tasks.get.return_value.execute.return_value = {
        "id": "t-del",
        "title": "Temporary Task",
        "status": "needsAction",
    }

    # Preview
    with patch("agent.services.tasks_service.get_tasks_service", return_value=mock_service):
        res_prev = tasks_service.delete_task(task_id="t-del", confirmed=False)

    assert res_prev["requires_confirmation"] is True
    assert res_prev["deleted"] is False
    mock_tasks.delete.assert_not_called()

    # Confirmed
    mock_tasks.delete.return_value.execute.return_value = {}
    with patch("agent.services.tasks_service.get_tasks_service", return_value=mock_service):
        res_conf = tasks_service.delete_task(task_id="t-del", confirmed=True)

    assert res_conf["deleted"] is True
    mock_tasks.delete.assert_called_once_with(tasklist="@default", task="t-del")

