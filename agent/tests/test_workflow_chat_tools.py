"""
tests/test_workflow_chat_tools.py
---------------------------------
Unit tests for LangChain workflow tools in chat: preview, confirmation,
listing, running, pausing, and history.
"""

from pathlib import Path
from unittest.mock import patch
import pytest

from agent.services import workflow_service
from agent.tools.workflow_tools import (
    WORKFLOW_TOOLS,
    create_workflow_plan,
    get_workflow_history,
    list_user_workflows,
    pause_workflow,
    resume_workflow,
    retry_last_failed_workflow,
    run_workflow_by_name,
)


@pytest.fixture
def chat_db(tmp_path: Path):
    db_file = tmp_path / "test_chat_workflows.db"
    workflow_service.init_workflow_db(db_file)
    with patch("agent.tools.workflow_tools.save_workflow") as mock_save, patch(
        "agent.services.workflow_service.DEFAULT_WORKFLOW_DB_PATH", db_file
    ):
        mock_save.side_effect = lambda wf: workflow_service.save_workflow(wf, db_path=db_file)
        yield db_file


def test_workflow_tools_have_names_and_invocation():
    for t in WORKFLOW_TOOLS:
        assert hasattr(t, "name")
        assert hasattr(t, "invoke")
        assert len(t.name) > 0


def test_create_workflow_plan_requires_confirmation_preview(chat_db):
    steps_json = '[{"id": "s1", "name": "Check tasks", "tool": "list_pending_tasks", "inputs": {}}]'

    # 1. First invocation with confirmed=False returns preview
    res_prev = create_workflow_plan.invoke(
        {
            "name": "Evening Review",
            "description": "Reviews tasks every evening",
            "trigger_type": "scheduled",
            "schedule_time": "19:00",
            "recurrence": "daily",
            "steps_json": steps_json,
            "confirmed": False,
        }
    )

    assert res_prev["success"] is True
    assert res_prev["created"] is False
    assert res_prev["requires_confirmation"] is True
    assert "Please confirm" in res_prev["message"]

    # 2. Confirmed invocation with confirmed=True saves and activates
    res_conf = create_workflow_plan.invoke(
        {
            "name": "Evening Review",
            "description": "Reviews tasks every evening",
            "trigger_type": "scheduled",
            "schedule_time": "19:00",
            "recurrence": "daily",
            "steps_json": steps_json,
            "confirmed": True,
        }
    )

    assert res_conf["success"] is True
    assert res_conf["created"] is True
    assert res_conf["requires_confirmation"] is False
    assert res_conf["workflow"]["name"] == "Evening Review"


def test_workflow_chat_tool_pause_and_resume(chat_db):
    wf_data = {
        "id": "wf_toggle_test",
        "name": "Toggle Me",
        "steps": [{"id": "s1", "tool": "get_today_events", "inputs": {}}],
        "status": "active",
    }
    workflow_service.save_workflow(wf_data, db_path=chat_db)

    # Pause
    with patch("agent.tools.workflow_tools.get_workflow", return_value=wf_data), patch(
        "agent.tools.workflow_tools.update_workflow_status",
        return_value={"name": "Toggle Me", "status": "paused"},
    ):
        res_pause = pause_workflow.invoke({"name_or_id": "wf_toggle_test"})
    assert res_pause["success"] is True
    assert "paused" in res_pause["message"]

    # Resume
    with patch("agent.tools.workflow_tools.get_workflow", return_value=wf_data), patch(
        "agent.tools.workflow_tools.update_workflow_status",
        return_value={"name": "Toggle Me", "status": "active"},
    ):
        res_resume = resume_workflow.invoke({"name_or_id": "wf_toggle_test"})
    assert res_resume["success"] is True
    assert "active" in res_resume["message"]


def test_retry_last_failed_workflow_handles_no_failed(chat_db):
    with patch("agent.tools.workflow_tools.list_executions", return_value=[]):
        res = retry_last_failed_workflow.invoke({})
    assert res["success"] is False
    assert "No failed workflow" in res["message"]
