"""
services/workflow_engine.py
---------------------------
Core Execution Engine for multi-step automated workflows.

Features:
  - Validates workflow definitions against allowed tool registries and DAG dependencies.
  - Resolves input templating (e.g. {{step_1.summary}}, {{all_outputs}}).
  - Evaluates safe conditional branching (e.g. {{step_1.count}} > 0).
  - Enforces Human-in-the-Loop approval safeguards on destructive/external actions.
  - Tracks step-level execution history, retries with backoff, and graceful failure handling.
"""

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.services.workflow_adapters import WORKFLOW_TOOL_REGISTRY, execute_tool
from agent.services.workflow_service import (
    create_approval,
    create_execution,
    get_execution,
    get_workflow,
    update_execution,
)
from agent.services.date_utils import to_utc_iso


def validate_workflow(workflow_data: dict[str, Any]) -> tuple[bool, str]:
    """
    Validate that a workflow definition has a name, valid steps, allowed tools,
    and valid step dependencies without circular references.
    """
    name = (workflow_data.get("name") or "").strip()
    if not name:
        return False, "Workflow name cannot be empty."

    steps = workflow_data.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        return False, "Workflow must contain at least one step in 'steps'."

    seen_step_ids: set[str] = set()
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"Step at index {idx} must be a dictionary."

        step_id = (step.get("id") or "").strip()
        if not step_id:
            return False, f"Step at index {idx} is missing a non-empty 'id'."
        if step_id in seen_step_ids:
            return False, f"Duplicate step ID '{step_id}' found in workflow."
        seen_step_ids.add(step_id)

        tool_name = step.get("tool")
        if not tool_name or tool_name not in WORKFLOW_TOOL_REGISTRY:
            allowed = list(WORKFLOW_TOOL_REGISTRY.keys())
            return (
                False,
                f"Step '{step_id}' uses unknown or unauthorized tool '{tool_name}'. Allowed: {allowed}",
            )

        # Check dependencies exist earlier in the list (prevents forward & circular references)
        depends_on = step.get("depends_on") or []
        if isinstance(depends_on, list):
            for dep in depends_on:
                if dep not in seen_step_ids:
                    return False, f"Step '{step_id}' depends on '{dep}' which is not defined before it."

    return True, "Valid"


def resolve_template_value(val: Any, context: dict[str, Any]) -> Any:
    """
    Interpolate {{step_id.key}} or {{all_outputs}} expressions from prior step outputs.
    """
    if isinstance(val, str):
        trimmed = val.strip()
        # Direct object replacements (e.g. {{all_outputs}})
        if trimmed == "{{all_outputs}}":
            return context.get("all_outputs", {})

        single_match = re.fullmatch(r"\{\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\}\}", trimmed)
        if single_match:
            step_name, prop_name = single_match.group(1), single_match.group(2)
            step_data = context.get(step_name, {})
            if isinstance(step_data, dict):
                return step_data.get(prop_name, "")
            return getattr(step_data, prop_name, "")

        # String substring interpolation
        def _replace_match(m: re.Match) -> str:
            s_name, p_name = m.group(1), m.group(2)
            s_data = context.get(s_name, {})
            if isinstance(s_data, dict):
                return str(s_data.get(p_name, ""))
            return str(getattr(s_data, p_name, ""))

        return re.sub(r"\{\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\}\}", _replace_match, val)

    elif isinstance(val, dict):
        return {k: resolve_template_value(v, context) for k, v in val.items()}
    elif isinstance(val, list):
        return [resolve_template_value(item, context) for item in val]
    return val


def evaluate_condition(condition_str: str | None, context: dict[str, Any]) -> bool:
    """
    Safely evaluate simple step conditions without using eval().
    Supports:
      - "{{step_1.count}} > 0"
      - "{{step_1.success}} == true"
      - "{{step_1.result}} != empty"
    """
    if not condition_str or not str(condition_str).strip():
        return True

    cond = str(condition_str).strip()
    # Resolve any templates in the condition
    resolved = resolve_template_value(cond, context)
    if not isinstance(resolved, str):
        return bool(resolved)

    # Simple comparisons: ==, !=, >, <, >=, <=
    m = re.match(
        r"^(.*?)\s*(==|!=|>=|<=|>|<)\s*(.*?)$", resolved, re.IGNORECASE
    )
    if not m:
        # Truthy check on a string/boolean
        lowered = resolved.lower()
        if lowered in {"false", "0", "null", "none", "", "empty"}:
            return False
        return True

    left_val = m.group(1).strip()
    op = m.group(2).strip()
    right_val = m.group(3).strip()

    # Try numeric conversion
    try:
        left_num = float(left_val)
        right_num = float(right_val)
        if op == ">":
            return left_num > right_num
        if op == "<":
            return left_num < right_num
        if op == ">=":
            return left_num >= right_num
        if op == "<=":
            return left_num <= right_num
        if op == "==":
            return left_num == right_num
        if op == "!=":
            return left_num != right_num
    except (ValueError, TypeError):
        pass

    # String / boolean comparison
    l_str = left_val.strip("\"'").lower()
    r_str = right_val.strip("\"'").lower()
    if r_str in {"empty", "none", "null"} and l_str in {"empty", "none", "null", ""}:
        return op == "=="
    if op == "==":
        return l_str == r_str
    if op == "!=":
        return l_str != r_str

    return True


def execute_workflow(
    workflow_id: str,
    trigger_type: str = "manual",
    execution_id: str | None = None,
    approved_step_id: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Execute a workflow definition step-by-step.
    Handles sequential flow, input interpolation, conditional branching,
    and human-in-the-loop approvals.
    """
    wf = get_workflow(workflow_id, db_path=db_path)
    if not wf:
        raise ValueError(f"Workflow '{workflow_id}' not found.")

    if wf["status"] == "paused" and trigger_type == "scheduled":
        return {"status": "skipped", "message": f"Workflow '{wf['name']}' is paused."}

    # Initialize or resume execution
    if execution_id:
        exec_record = get_execution(execution_id, db_path=db_path)
        if not exec_record:
            raise ValueError(f"Execution '{execution_id}' not found.")
    else:
        exec_record = create_execution(wf["id"], trigger_type=trigger_type, db_path=db_path)

    exec_id = exec_record["id"]
    steps = wf["steps"]
    step_results = dict(exec_record.get("step_results") or {})
    start_index = exec_record.get("current_step_index", 0)

    # Build initial context from prior completed steps
    context: dict[str, Any] = {"all_outputs": {}}
    for s_id, s_info in step_results.items():
        if isinstance(s_info, dict) and "output" in s_info:
            context[s_id] = s_info["output"]
            context["all_outputs"][s_id] = s_info["output"]

    for idx in range(start_index, len(steps)):
        step = steps[idx]
        step_id = step["id"]
        step_name = step.get("name", step_id)
        tool_name = step["tool"]
        raw_inputs = step.get("inputs") or {}
        condition = step.get("condition")
        depends_on = step.get("depends_on") or []

        # 1. Check prerequisite dependencies
        prereq_failed = any(
            step_results.get(dep, {}).get("status") in {"failed", "skipped"}
            for dep in depends_on
        )
        if prereq_failed:
            step_results[step_id] = {
                "name": step_name,
                "tool": tool_name,
                "status": "skipped",
                "reason": "Prerequisite step failed or was skipped",
                "completed_at": to_utc_iso(datetime.now(timezone.utc)),
            }
            update_execution(
                exec_id,
                status="running",
                step_results={step_id: step_results[step_id]},
                current_step_index=idx + 1,
                db_path=db_path,
            )
            continue

        # 2. Evaluate conditional branching
        if condition and not evaluate_condition(condition, context):
            step_results[step_id] = {
                "name": step_name,
                "tool": tool_name,
                "status": "skipped",
                "reason": f"Condition evaluated to false ({condition})",
                "completed_at": to_utc_iso(datetime.now(timezone.utc)),
            }
            update_execution(
                exec_id,
                status="running",
                step_results={step_id: step_results[step_id]},
                current_step_index=idx + 1,
                db_path=db_path,
            )
            continue

        # 3. Resolve templated inputs from prior steps
        resolved_inputs = resolve_template_value(raw_inputs, context)

        # 4. Check Human-in-the-Loop approval requirements
        tool_meta = WORKFLOW_TOOL_REGISTRY.get(tool_name, {})
        requires_approval = step.get("requires_approval")
        if requires_approval is None:
            requires_approval = tool_meta.get("requires_approval", False)

        # If approval is required and this step was not just approved by the user
        if requires_approval and approved_step_id != step_id:
            preview_text = (
                f"Workflow '{wf['name']}' requests approval for step '{step_name}'.\n"
                f"Tool: {tool_name}\nArguments: {resolved_inputs}"
            )
            appr = create_approval(
                execution_id=exec_id,
                workflow_id=wf["id"],
                step_id=step_id,
                tool_name=tool_name,
                tool_args=resolved_inputs,
                preview=preview_text,
                db_path=db_path,
            )
            step_results[step_id] = {
                "name": step_name,
                "tool": tool_name,
                "status": "pending_approval",
                "approval_id": appr["id"],
                "preview": preview_text,
                "started_at": to_utc_iso(datetime.now(timezone.utc)),
            }
            return update_execution(
                exec_id,
                status="pending_approval",
                step_results={step_id: step_results[step_id]},
                current_step_index=idx,
                pending_approval=appr,
                db_path=db_path,
            )

        # 5. Execute step with retry handling
        max_retries = int(step.get("retry_count", 0))
        last_error = ""
        output: Any = None
        succeeded = False

        step_start_time = to_utc_iso(datetime.now(timezone.utc))

        for attempt in range(max_retries + 1):
            try:
                output = execute_tool(tool_name, resolved_inputs)
                succeeded = True
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < max_retries:
                    time.sleep(0.5 * (attempt + 1))

        step_finish_time = to_utc_iso(datetime.now(timezone.utc))

        if succeeded:
            step_results[step_id] = {
                "name": step_name,
                "tool": tool_name,
                "status": "completed",
                "output": output,
                "started_at": step_start_time,
                "completed_at": step_finish_time,
            }
            context[step_id] = output
            context["all_outputs"][step_id] = output
            update_execution(
                exec_id,
                status="running",
                step_results={step_id: step_results[step_id]},
                current_step_index=idx + 1,
                pending_approval=None,
                db_path=db_path,
            )
        else:
            on_failure = step.get("on_failure", "stop")
            step_results[step_id] = {
                "name": step_name,
                "tool": tool_name,
                "status": "failed",
                "error": last_error,
                "started_at": step_start_time,
                "completed_at": step_finish_time,
            }
            if on_failure == "continue":
                update_execution(
                    exec_id,
                    status="running",
                    step_results={step_id: step_results[step_id]},
                    current_step_index=idx + 1,
                    db_path=db_path,
                )
            else:
                # Terminate execution as failed
                return update_execution(
                    exec_id,
                    status="failed",
                    step_results={step_id: step_results[step_id]},
                    current_step_index=idx,
                    error_message=f"Step '{step_name}' failed: {last_error}",
                    db_path=db_path,
                )

    # All steps completed successfully
    return update_execution(
        exec_id,
        status="completed",
        step_results=step_results,
        current_step_index=len(steps),
        pending_approval=None,
        db_path=db_path,
    )


def approve_and_resume_execution(
    execution_id: str,
    approval_id: str,
    decision: str = "approved",
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Resolve a pending approval and either resume execution or cancel it."""
    from agent.services.workflow_service import resolve_approval

    resolve_approval(approval_id, decision=decision, db_path=db_path)
    exec_rec = get_execution(execution_id, db_path=db_path)
    if not exec_rec:
        raise ValueError(f"Execution '{execution_id}' not found.")

    if decision == "rejected":
        return update_execution(
            execution_id,
            status="cancelled",
            error_message="Execution was cancelled by the user upon approval prompt.",
            pending_approval=None,
            db_path=db_path,
        )

    # If approved, resume execution
    pending_info = exec_rec.get("pending_approval") or {}
    step_id = pending_info.get("step_id")
    return execute_workflow(
        workflow_id=exec_rec["workflow_id"],
        execution_id=execution_id,
        approved_step_id=step_id,
        db_path=db_path,
    )
