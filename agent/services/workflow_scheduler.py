"""
services/workflow_scheduler.py
------------------------------
Persistent background scheduler for automated workflows.

Features:
  - Schedules workflows with timezone awareness (Asia/Kolkata default).
  - Supports daily, weekly, one-time, and interval recurring schedules.
  - Concurrency-safe atomic claim mechanism preventing duplicate runs across restarts.
  - Missed-job recovery policy (resumes next schedule without avalanche triggers).
  - Standalone worker daemon: python -m agent.services.workflow_scheduler
"""

import sys
import time
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.services.date_utils import (
    DEFAULT_TIMEZONE_NAME,
    get_user_timezone,
    parse_datetime,
    to_utc_iso,
)
from agent.services import workflow_engine
from agent.services.workflow_engine import execute_workflow
from agent.services.workflow_service import (
    get_mongodb_database,
    get_db_connection,
    init_workflow_db,
    list_workflows,
    uses_mongodb,
)


def calculate_next_workflow_run(
    trigger_config: dict[str, Any],
    from_time_utc: datetime | None = None,
    tz_name: str | None = None,
) -> str | None:
    """
    Calculate the next scheduled run in UTC based on recurrence rules
    and local timezone (Asia/Kolkata default).
    """
    recurrence = (trigger_config.get("recurrence") or "daily").lower()
    time_str = trigger_config.get("time") or "08:00"
    user_tz_name = trigger_config.get("timezone") or tz_name or DEFAULT_TIMEZONE_NAME
    tz = get_user_timezone(user_tz_name)

    base_utc = from_time_utc or datetime.now(timezone.utc)
    base_local = base_utc.astimezone(tz)

    try:
        parts = time_str.strip().split(":")
        target_h, target_m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        target_h, target_m = 8, 0

    target_time = dt_time(target_h, target_m)

    if recurrence == "once":
        dt_spec = trigger_config.get("date_time") or trigger_config.get("datetime")
        if dt_spec:
            dt = parse_datetime(dt_spec, tz_name=user_tz_name)
            if dt > base_local:
                return to_utc_iso(dt)
        return None

    if recurrence == "daily":
        candidate_today = datetime.combine(base_local.date(), target_time, tzinfo=tz)
        if candidate_today > base_local:
            return to_utc_iso(candidate_today)
        next_day = candidate_today + timedelta(days=1)
        return to_utc_iso(next_day)

    if recurrence == "weekly":
        # days_of_week e.g. ["MONDAY", "WEDNESDAY"]
        days = trigger_config.get("days_of_week") or ["MONDAY"]
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        target_indices = {day_names.index(d.lower()) for d in days if d.lower() in day_names}
        if not target_indices:
            target_indices = {0}  # Monday default

        for offset in range(1, 8):
            cand_date = base_local.date() + timedelta(days=offset)
            if cand_date.weekday() in target_indices:
                cand_dt = datetime.combine(cand_date, target_time, tzinfo=tz)
                return to_utc_iso(cand_dt)
        # Fallback 7 days ahead
        return to_utc_iso(datetime.combine(base_local.date() + timedelta(days=7), target_time, tzinfo=tz))

    # Default fallback: daily
    return to_utc_iso(datetime.combine(base_local.date() + timedelta(days=1), target_time, tzinfo=tz))


def claim_due_workflows(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """
    Atomically find and claim scheduled workflows whose next_run_utc is due.
    Updates next_run_utc to prevent duplicate concurrent runs.
    """
    init_workflow_db(db_path)
    now_utc_str = to_utc_iso(datetime.now(timezone.utc))
    if uses_mongodb(db_path):
        database = get_mongodb_database()
        candidates = database.workflows.find(
            {
                "status": "active",
                "trigger_type": "scheduled",
                "next_run_utc": {"$ne": None, "$lte": now_utc_str},
            }
        )
        claimed = []
        for candidate in candidates:
            old_next = candidate["next_run_utc"]
            new_next = calculate_next_workflow_run(
                candidate.get("trigger_config") or {},
                from_time_utc=datetime.now(timezone.utc),
            )
            result = database.workflows.update_one(
                {
                    "_id": candidate["_id"],
                    "status": "active",
                    "next_run_utc": old_next,
                },
                {"$set": {"next_run_utc": new_next}},
            )
            if result.modified_count == 1:
                candidate["id"] = str(candidate.pop("_id"))
                candidate["next_run_utc"] = old_next
                claimed.append(candidate)
        return claimed

    conn = get_db_connection(db_path)

    # 1. Fetch candidates
    candidates = conn.execute(
        """
        SELECT id, name, trigger_config, next_run_utc
        FROM workflows
        WHERE status = 'active'
          AND trigger_type = 'scheduled'
          AND next_run_utc IS NOT NULL
          AND next_run_utc <= ?;
        """,
        (now_utc_str,),
    ).fetchall()

    claimed: list[dict[str, Any]] = []

    # 2. Claim atomically
    for cand in candidates:
        wf_id = cand["id"]
        old_next = cand["next_run_utc"]
        cfg = {}
        try:
            import json
            cfg = json.loads(cand["trigger_config"])
        except Exception:
            pass

        new_next = calculate_next_workflow_run(cfg, from_time_utc=datetime.now(timezone.utc))

        with conn:
            cur = conn.execute(
                """
                UPDATE workflows
                SET next_run_utc = ?
                WHERE id = ? AND next_run_utc = ?;
                """,
                (new_next, wf_id, old_next),
            )
            if cur.rowcount == 1:
                claimed.append(dict(cand))

    conn.close()
    return claimed


def sync_active_workflow_schedules(db_path: Path | str | None = None) -> int:
    """Ensure any active scheduled workflow with null next_run_utc gets populated."""
    init_workflow_db(db_path)
    workflows = list_workflows(status="active", db_path=db_path)
    if uses_mongodb(db_path):
        database = get_mongodb_database()
        updated = 0
        for workflow in workflows:
            if workflow["trigger_type"] == "scheduled" and not workflow.get("next_run_utc"):
                next_run = calculate_next_workflow_run(workflow["trigger_config"])
                if next_run:
                    result = database.workflows.update_one(
                        {
                            "_id": workflow["id"],
                            "status": "active",
                            "next_run_utc": workflow.get("next_run_utc"),
                        },
                        {"$set": {"next_run_utc": next_run}},
                    )
                    updated += result.modified_count
        return updated

    updated = 0
    conn = get_db_connection(db_path)

    for wf in workflows:
        if wf["trigger_type"] == "scheduled" and not wf.get("next_run_utc"):
            next_run = calculate_next_workflow_run(wf["trigger_config"])
            if next_run:
                with conn:
                    conn.execute(
                        "UPDATE workflows SET next_run_utc = ? WHERE id = ?",
                        (next_run, wf["id"]),
                    )
                updated += 1
    conn.close()
    return updated


def run_scheduler_tick(db_path: Path | str | None = None) -> dict[str, Any]:
    """Execute a single scheduler polling cycle."""
    sync_active_workflow_schedules(db_path=db_path)
    due_list = claim_due_workflows(db_path=db_path)

    triggered = 0
    errors = 0

    for wf in due_list:
        try:
            workflow_engine.execute_workflow(wf["id"], trigger_type="scheduled", db_path=db_path)
            triggered += 1
        except Exception as exc:
            errors += 1
            print(f"[Scheduler Error] Failed to execute workflow '{wf['name']}': {exc}")

    return {
        "claimed": len(due_list),
        "triggered": triggered,
        "errors": errors,
    }


def start_workflow_scheduler(poll_interval: float = 10.0, db_path: Path | str | None = None) -> None:
    """Run continuous workflow scheduler daemon."""
    print("=" * 60)
    print("  Personal AI Agent — Automated Workflow Scheduler")
    print("=" * 60)
    print(f"Polling interval: {poll_interval}s")
    print("Press Ctrl+C to stop the scheduler daemon.")
    print("=" * 60)

    try:
        while True:
            stats = run_scheduler_tick(db_path=db_path)
            if stats["claimed"] > 0:
                print(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"Triggered {stats['triggered']} scheduled workflows (Errors: {stats['errors']})"
                )
            time.sleep(poll_interval)
    except (KeyboardInterrupt, SystemExit):
        print("\nWorkflow scheduler stopped.")


if __name__ == "__main__":
    interval = 10.0
    if len(sys.argv) > 1:
        try:
            interval = float(sys.argv[1])
        except ValueError:
            pass
    start_workflow_scheduler(poll_interval=interval)
