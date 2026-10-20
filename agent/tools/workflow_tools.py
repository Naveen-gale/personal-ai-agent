"""
tools/workflow_tools.py
-----------------------
LangChain tools for natural-language workflow automation control.
Enables creating, listing, running, pausing, and inspecting workflows in chat.
"""

import json
from typing import Any
from langchain_core.tools import tool

from agent.services.workflow_engine import execute_workflow, validate_workflow
from agent.services.workflow_scheduler import calculate_next_workflow_run
from agent.services.workflow_service import (
    get_workflow,
    list_executions,
    list_workflows,
    save_workflow,
    update_workflow_status,
)


@tool
def create_workflow_plan(
    name: str,
    description: str,
    trigger_type: str = "manual",
    schedule_time: str = "08:00",
    recurrence: str = "daily",
    steps_json: str = "[]",
    confirmed: bool = False,
) -> dict:
    """Preview workflow when confirmed=False; save and activate only when confirmed=True after user approves."""
    try:
        try:
            steps = json.loads(steps_json) if isinstance(steps_json, str) else steps_json
        except Exception:
            return {"success": False, "message": "steps_json must be valid JSON array of steps."}

        trigger_config = {"recurrence": recurrence, "time": schedule_time, "timezone": "Asia/Kolkata"}
        wf_data = {
            "name": name.strip(),
            "description": description.strip(),
            "trigger_type": trigger_type.strip().lower(),
            "trigger_config": trigger_config,
            "steps": steps,
            "status": "active",
        }

        is_valid, msg = validate_workflow(wf_data)
        if not is_valid:
            return {"success": False, "message": f"Workflow validation error: {msg}"}

        if trigger_type.strip().lower() == "scheduled":
            wf_data["next_run_utc"] = calculate_next_workflow_run(trigger_config)

        if not confirmed:
            return {
                "success": True,
                "created": False,
                "requires_confirmation": True,
                "preview": {
                    "name": name,
                    "description": description,
                    "trigger_type": trigger_type,
                    "trigger_config": trigger_config,
                    "step_count": len(steps),
                    "steps": [{"id": s.get("id"), "name": s.get("name"), "tool": s.get("tool")} for s in steps],
                },
                "message": (
                    f"Please confirm: Create and activate workflow '{name}' with {len(steps)} steps? "
                    f"(Type 'yes' to proceed)"
                ),
            }

        saved = save_workflow(wf_data)
        return {
            "success": True,
            "created": True,
            "requires_confirmation": False,
            "workflow": saved,
            "message": f"Workflow '{name}' created and activated successfully.",
        }
    except Exception as error:
        return {"success": False, "created": False, "message": f"Failed to create workflow: {error}"}


@tool
def list_user_workflows(status: str = "all") -> dict:
    """List all saved workflows and their current status (active, paused, draft)."""
    try:
        workflows = list_workflows(status=status)
        return {"success": True, "workflows": workflows, "count": len(workflows)}
    except Exception as error:
        return {"success": False, "workflows": [], "count": 0, "message": f"Failed to list workflows: {error}"}


@tool
def run_workflow_by_name(name_or_id: str) -> dict:
    """Trigger manual execution of a workflow by its name or ID."""
    try:
        wf = get_workflow(name_or_id)
        if not wf:
            return {"success": False, "message": f"Workflow '{name_or_id}' was not found."}

        res = execute_workflow(wf["id"], trigger_type="manual")
        return {
            "success": res.get("status") in {"completed", "running", "pending_approval"},
            "execution": res,
            "message": f"Workflow '{wf['name']}' execution finished with status: {res.get('status')}.",
        }
    except Exception as error:
        return {"success": False, "message": f"Failed to run workflow: {error}"}


@tool
def pause_workflow(name_or_id: str) -> dict:
    """Pause an active workflow so its scheduled runs are halted."""
    try:
        wf = get_workflow(name_or_id)
        if not wf:
            return {"success": False, "message": f"Workflow '{name_or_id}' was not found."}

        updated = update_workflow_status(wf["id"], new_status="paused")
        return {"success": True, "workflow": updated, "message": f"Workflow '{wf['name']}' is now paused."}
    except Exception as error:
        return {"success": False, "message": f"Failed to pause workflow: {error}"}


@tool
def resume_workflow(name_or_id: str) -> dict:
    """Resume a paused workflow and re-enable its schedule."""
    try:
        wf = get_workflow(name_or_id)
        if not wf:
            return {"success": False, "message": f"Workflow '{name_or_id}' was not found."}

        updated = update_workflow_status(wf["id"], new_status="active")
        return {"success": True, "workflow": updated, "message": f"Workflow '{wf['name']}' is now active."}
    except Exception as error:
        return {"success": False, "message": f"Failed to resume workflow: {error}"}


@tool
def get_workflow_history(name_or_id: str, limit: int = 5) -> dict:
    """Retrieve execution history logs for a specific workflow."""
    try:
        wf = get_workflow(name_or_id)
        if not wf:
            return {"success": False, "message": f"Workflow '{name_or_id}' was not found."}

        executions = list_executions(workflow_id=wf["id"], limit=limit)
        return {"success": True, "workflow_name": wf["name"], "executions": executions, "count": len(executions)}
    except Exception as error:
        return {"success": False, "executions": [], "count": 0, "message": f"Failed to get history: {error}"}


@tool
def retry_last_failed_workflow() -> dict:
    """Find and retry the most recent failed workflow execution."""
    try:
        all_execs = list_executions(limit=20)
        failed = next((e for e in all_execs if e["status"] == "failed"), None)
        if not failed:
            return {"success": False, "message": "No failed workflow executions found to retry."}

        res = execute_workflow(failed["workflow_id"], trigger_type="retry")
        return {
            "success": True,
            "retried_execution_id": failed["id"],
            "new_execution": res,
            "message": f"Retried execution for workflow '{failed['workflow_name']}'. New status: {res.get('status')}",
        }
    except Exception as error:
        return {"success": False, "message": f"Failed to retry workflow: {error}"}


WORKFLOW_TOOLS = [
    create_workflow_plan,
    list_user_workflows,
    run_workflow_by_name,
    pause_workflow,
    resume_workflow,
    get_workflow_history,
    retry_last_failed_workflow,
]
