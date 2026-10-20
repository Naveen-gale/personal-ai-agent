"""
tests/test_workflow_scheduler.py
--------------------------------
Unit tests for the Workflow Scheduler: recurrence calculations,
atomic concurrency claim, duplicate run prevention, and tick processing.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent.services import workflow_scheduler, workflow_service
from agent.services.date_utils import to_utc_iso


@pytest.fixture
def sched_db(tmp_path: Path):
    db_file = tmp_path / "test_sched.db"
    workflow_service.init_workflow_db(db_file)
    return db_file


def test_calculate_next_workflow_run_daily():
    config = {"recurrence": "daily", "time": "08:00", "timezone": "Asia/Kolkata"}
    # From 05:00 UTC (10:30 AM IST), 08:00 AM IST has passed, next run should be tomorrow
    base_utc = datetime(2026, 10, 20, 5, 0, 0, tzinfo=timezone.utc)
    next_run = workflow_scheduler.calculate_next_workflow_run(config, from_time_utc=base_utc)
    assert next_run is not None
    # 08:00 IST is 02:30 UTC
    assert "02:30:00Z" in next_run
    assert "2026-10-21" in next_run


def test_calculate_next_workflow_run_weekly():
    config = {
        "recurrence": "weekly",
        "time": "10:00",
        "days_of_week": ["MONDAY"],
        "timezone": "Asia/Kolkata",
    }
    base_utc = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)  # Tuesday
    next_run = workflow_scheduler.calculate_next_workflow_run(config, from_time_utc=base_utc)
    assert next_run is not None
    # Next Monday from Tuesday Oct 20 is Oct 26
    assert "2026-10-26" in next_run


def test_claim_due_workflows_atomic_concurrency(sched_db):
    now_utc = to_utc_iso(datetime.now(timezone.utc))
    wf = {
        "id": "wf_due_1",
        "name": "Due Workflow",
        "trigger_type": "scheduled",
        "trigger_config": {"recurrence": "daily", "time": "08:00"},
        "steps": [{"id": "s1", "tool": "get_today_events", "inputs": {}}],
        "status": "active",
        "next_run_utc": now_utc,
    }
    workflow_service.save_workflow(wf, db_path=sched_db)

    # First claim succeeds
    claimed_1 = workflow_scheduler.claim_due_workflows(db_path=sched_db)
    assert len(claimed_1) == 1
    assert claimed_1[0]["id"] == "wf_due_1"

    # Second concurrent claim must return nothing (already claimed and next_run_utc bumped)
    claimed_2 = workflow_scheduler.claim_due_workflows(db_path=sched_db)
    assert len(claimed_2) == 0


def test_run_scheduler_tick_triggers_execution(sched_db):
    past_utc = to_utc_iso(datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc))
    wf = {
        "id": "wf_tick_test",
        "name": "Tick Workflow",
        "trigger_type": "scheduled",
        "trigger_config": {"recurrence": "daily", "time": "08:00"},
        "steps": [{"id": "s1", "tool": "get_today_events", "inputs": {}}],
        "status": "active",
        "next_run_utc": past_utc,
    }
    workflow_service.save_workflow(wf, db_path=sched_db)

    with patch(
        "agent.services.workflow_engine.execute_workflow",
        return_value={"status": "completed"},
    ) as mock_exec:
        stats = workflow_scheduler.run_scheduler_tick(db_path=sched_db)

    assert stats["claimed"] == 1
    assert stats["triggered"] == 1
    mock_exec.assert_called_once_with("wf_tick_test", trigger_type="scheduled", db_path=sched_db)
