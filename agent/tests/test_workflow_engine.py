"""
tests/test_workflow_engine.py
-----------------------------
Unit tests for the Workflow Execution Engine: validation, execution,
input templating, conditional branching, retries, and human approvals.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent.services import workflow_engine, workflow_service


@pytest.fixture
def workflow_db(tmp_path: Path):
    """Isolated SQLite database for workflow testing."""
    db_file = tmp_path / "test_workflows.db"
    workflow_service.init_workflow_db(db_file)
    return db_file


def test_validate_workflow_checks_required_fields():
    # Empty name
    valid, msg = workflow_engine.validate_workflow({"name": "", "steps": []})
    assert not valid
    assert "name cannot be empty" in msg

    # Empty steps
    valid, msg = workflow_engine.validate_workflow({"name": "Test", "steps": []})
    assert not valid
    assert "at least one step" in msg

    # Unauthorized tool
    valid, msg = workflow_engine.validate_workflow(
        {"name": "Bad Tool", "steps": [{"id": "s1", "tool": "rm_rf_database"}]}
    )
    assert not valid
    assert "unauthorized tool" in msg

    # Missing dependency
    valid, msg = workflow_engine.validate_workflow(
        {
            "name": "Missing Dep",
            "steps": [
                {"id": "s1", "tool": "get_today_events", "depends_on": ["non_existent_step"]}
            ],
        }
    )
    assert not valid
    assert "depends on 'non_existent_step'" in msg


def test_resolve_template_values():
    context = {
        "step_1": {"count": 4, "summary": "Urgent emails found"},
        "all_outputs": {"step_1": {"count": 4}},
    }

    # Direct variable substitution
    assert workflow_engine.resolve_template_value("{{step_1.count}}", context) == 4

    # String interpolation
    res_str = workflow_engine.resolve_template_value(
        "Subject: Summary with count {{step_1.count}}", context
    )
    assert res_str == "Subject: Summary with count 4"

    # All outputs
    assert workflow_engine.resolve_template_value("{{all_outputs}}", context) == {
        "step_1": {"count": 4}
    }


def test_evaluate_conditions():
    context = {"step_1": {"count": 3, "success": True, "result": "Done"}}

    assert workflow_engine.evaluate_condition("{{step_1.count}} > 0", context) is True
    assert workflow_engine.evaluate_condition("{{step_1.count}} > 5", context) is False
    assert workflow_engine.evaluate_condition("{{step_1.count}} == 3", context) is True
    assert workflow_engine.evaluate_condition("{{step_1.success}} == true", context) is True
    assert workflow_engine.evaluate_condition("", context) is True


def test_sequential_workflow_execution_success(workflow_db):
    wf_data = {
        "id": "wf_test_seq",
        "name": "Sequential Test Workflow",
        "steps": [
            {"id": "step_1", "tool": "get_today_events", "inputs": {}},
            {"id": "step_2", "tool": "list_pending_tasks", "inputs": {}},
        ],
    }
    workflow_service.save_workflow(wf_data, db_path=workflow_db)

    def mock_tool_call(tool_name, arguments):
        if tool_name == "get_today_events":
            return {"events": [{"id": "ev1", "title": "Standup"}], "count": 1}
        if tool_name == "list_pending_tasks":
            return {"tasks": [{"id": "t1", "title": "Study Python"}], "count": 1}
        return {}

    with patch("agent.services.workflow_engine.execute_tool", side_effect=mock_tool_call):
        exec_res = workflow_engine.execute_workflow("wf_test_seq", db_path=workflow_db)

    assert exec_res["status"] == "completed"
    assert exec_res["current_step_index"] == 2
    step_results = exec_res["step_results"]
    assert step_results["step_1"]["status"] == "completed"
    assert step_results["step_2"]["status"] == "completed"


def test_conditional_branching_skips_step(workflow_db):
    wf_data = {
        "id": "wf_test_cond",
        "name": "Conditional Test",
        "steps": [
            {"id": "step_1", "tool": "get_unread_emails", "inputs": {}},
            {
                "id": "step_2",
                "tool": "create_task",
                "condition": "{{step_1.count}} > 5",
                "inputs": {"title": "Check emails"},
            },
        ],
    }
    workflow_service.save_workflow(wf_data, db_path=workflow_db)

    def mock_tool_call(tool_name, arguments):
        if tool_name == "get_unread_emails":
            return {"emails": [], "count": 0}
        return {}

    with patch("agent.services.workflow_engine.execute_tool", side_effect=mock_tool_call):
        exec_res = workflow_engine.execute_workflow("wf_test_cond", db_path=workflow_db)

    assert exec_res["status"] == "completed"
    # Step 2 should be skipped because count (0) is not > 5
    assert exec_res["step_results"]["step_2"]["status"] == "skipped"


def test_human_approval_pauses_and_resumes_execution(workflow_db):
    wf_data = {
        "id": "wf_test_approval",
        "name": "Approval Required Test",
        "steps": [
            {"id": "step_1", "tool": "list_pending_tasks", "inputs": {}},
            {
                "id": "step_2",
                "tool": "send_email",
                "inputs": {
                    "recipient": "colleague@example.com",
                    "subject": "Tasks Update",
                    "body": "Here is the update.",
                },
                "requires_approval": True,
            },
        ],
    }
    workflow_service.save_workflow(wf_data, db_path=workflow_db)

    def mock_tool_call(tool_name, arguments):
        if tool_name == "list_pending_tasks":
            return {"tasks": [], "count": 0}
        if tool_name == "send_email":
            return {"success": True, "message_id": "sent-123"}
        return {}

    with patch("agent.services.workflow_engine.execute_tool", side_effect=mock_tool_call):
        # Step 1 should complete, step 2 should pause execution for approval
        exec_res = workflow_engine.execute_workflow("wf_test_approval", db_path=workflow_db)

        assert exec_res["status"] == "pending_approval"
        assert exec_res["step_results"]["step_1"]["status"] == "completed"
        assert exec_res["step_results"]["step_2"]["status"] == "pending_approval"
        approval_info = exec_res["pending_approval"]
        assert approval_info is not None

        # Resume with approval
        resumed = workflow_engine.approve_and_resume_execution(
            execution_id=exec_res["id"],
            approval_id=approval_info["id"],
            decision="approved",
            db_path=workflow_db,
        )

    assert resumed["status"] == "completed"
    assert resumed["step_results"]["step_2"]["status"] == "completed"
