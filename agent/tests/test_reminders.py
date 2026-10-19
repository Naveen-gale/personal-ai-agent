"""
tests/test_reminders.py
-----------------------
Unit tests for the Scheduled Reminder Engine, SQLite persistence,
atomic concurrency claim, recurrence calculation, worker restart recovery,
and multi-channel notification adapters.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from agent.services import reminder_service, reminder_worker
from agent.services.notification_service import (
    ConsoleDeliveryAdapter,
    TelegramDeliveryAdapter,
    get_delivery_adapter,
)
from agent.services.date_utils import to_utc_iso


@pytest.fixture
def test_db(tmp_path: Path):
    """Provide a clean isolated SQLite database for each test."""
    db_file = tmp_path / "test_reminders.db"
    reminder_service.init_db(db_file)
    return db_file


def test_create_reminder_safeguard_and_execution(test_db):
    # Preview
    res_prev = reminder_service.create_reminder(
        reminder_text="Study Python",
        scheduled_time="tomorrow at 10 AM",
        delivery_channel="telegram",
        confirmed=False,
        db_path=test_db,
    )
    assert res_prev["success"] is True
    assert res_prev["created"] is False
    assert res_prev["requires_confirmation"] is True
    assert "Study Python" in res_prev["message"]

    # Verify nothing was saved in DB
    listed = reminder_service.list_reminders(db_path=test_db)
    assert listed["count"] == 0

    # Confirmed execution
    res_conf = reminder_service.create_reminder(
        reminder_text="Study Python",
        scheduled_time="tomorrow at 10 AM",
        delivery_channel="telegram",
        confirmed=True,
        db_path=test_db,
    )
    assert res_conf["success"] is True
    assert res_conf["created"] is True
    assert res_conf["requires_confirmation"] is False

    # Verify saved in DB with pending status
    listed = reminder_service.list_reminders(db_path=test_db)
    assert listed["count"] == 1
    assert listed["reminders"][0]["text"] == "Study Python"
    assert listed["reminders"][0]["status"] == "pending"


def test_create_reminder_rejects_past_time(test_db):
    with pytest.raises(ValueError, match="in the past"):
        reminder_service.create_reminder(
            reminder_text="Past Reminder",
            scheduled_time="2020-01-01 10:00",
            confirmed=False,
            db_path=test_db,
        )


def test_calculate_next_occurrence_daily_and_weekly():
    current_utc = "2026-10-20T10:00:00Z"

    next_daily = reminder_service.calculate_next_occurrence(
        current_utc_iso=current_utc,
        recurrence_rule="daily",
        tz_name="Asia/Kolkata",
    )
    assert next_daily == "2026-10-21T10:00:00Z"

    next_weekly = reminder_service.calculate_next_occurrence(
        current_utc_iso=current_utc,
        recurrence_rule="weekly",
        tz_name="Asia/Kolkata",
    )
    assert next_weekly == "2026-10-27T10:00:00Z"


def test_calculate_next_occurrence_validates_rule_and_handles_weekday_time():
    current_utc = "2026-10-20T10:00:00Z"
    next_monday = reminder_service.calculate_next_occurrence(
        current_utc_iso=current_utc,
        recurrence_rule="weekly:monday",
        tz_name="Asia/Kolkata",
    )
    next_morning = reminder_service.calculate_next_occurrence(
        current_utc_iso=current_utc,
        recurrence_rule="every_morning:07:15",
        tz_name="Asia/Kolkata",
    )

    assert next_monday == "2026-10-26T10:00:00Z"
    assert next_morning == "2026-10-21T01:45:00Z"
    with pytest.raises(ValueError, match="Unsupported recurrence rule"):
        reminder_service.calculate_next_occurrence(
            current_utc_iso=current_utc,
            recurrence_rule="weekly:notaday",
            tz_name="Asia/Kolkata",
        )
    with pytest.raises(ValueError, match="valid 24-hour"):
        reminder_service.calculate_next_occurrence(
            current_utc_iso=current_utc,
            recurrence_rule="every_evening:29:00",
            tz_name="Asia/Kolkata",
        )


def test_create_reminder_rejects_unknown_recurrence_and_channel(test_db):
    with pytest.raises(ValueError, match="Unsupported recurrence rule"):
        reminder_service.create_reminder(
            reminder_text="Test",
            scheduled_time="tomorrow at 10 AM",
            recurrence_rule="monthly",
            db_path=test_db,
        )
    with pytest.raises(ValueError, match="Delivery channel"):
        reminder_service.create_reminder(
            reminder_text="Test",
            scheduled_time="tomorrow at 10 AM",
            delivery_channel="unsupported",
            db_path=test_db,
        )


def test_atomic_claim_concurrency_safety(test_db):
    # Insert a due reminder directly into DB
    conn = reminder_service.get_db_connection(test_db)
    past_due_utc = to_utc_iso(datetime.now(timezone.utc) - timedelta(minutes=5))
    with conn:
        conn.execute(
            """
            INSERT INTO reminders (
                reminder_id, user_id, reminder_text, scheduled_utc,
                user_timezone, recurrence_rule, delivery_channel,
                recipient_id, status, retry_count, last_delivery_result,
                created_at, updated_at
            ) VALUES ('r-due-1', 'default', 'Take Medicine', ?, 'Asia/Kolkata', NULL, 'console', NULL, 'pending', 0, NULL, ?, ?);
            """,
            (past_due_utc, past_due_utc, past_due_utc),
        )
    conn.close()

    # First claim should succeed
    claimed_1 = reminder_service.claim_due_reminders(limit=10, db_path=test_db)
    assert len(claimed_1) == 1
    assert claimed_1[0]["reminder_id"] == "r-due-1"

    # Second concurrent claim must NOT return the same reminder (already claimed!)
    claimed_2 = reminder_service.claim_due_reminders(limit=10, db_path=test_db)
    assert len(claimed_2) == 0


def test_worker_recovers_stale_claims_after_crash(test_db):
    conn = reminder_service.get_db_connection(test_db)
    stale_time = to_utc_iso(datetime.now(timezone.utc) - timedelta(minutes=10))
    with conn:
        conn.execute(
            """
            INSERT INTO reminders (
                reminder_id, user_id, reminder_text, scheduled_utc,
                user_timezone, recurrence_rule, delivery_channel,
                recipient_id, status, retry_count, last_delivery_result,
                created_at, updated_at
            ) VALUES ('r-stale', 'default', 'Stale Task', ?, 'Asia/Kolkata', NULL, 'console', NULL, 'claimed', 0, NULL, ?, ?);
            """,
            (stale_time, stale_time, stale_time),
        )
    conn.close()

    # Worker recovery
    recovered = reminder_service.recover_stale_claims(stale_minutes=5, db_path=test_db)
    assert recovered == 1

    # Check status reset to pending
    conn = reminder_service.get_db_connection(test_db)
    row = conn.execute("SELECT status FROM reminders WHERE reminder_id = 'r-stale'").fetchone()
    conn.close()
    assert row["status"] == "pending"


def test_mark_reminder_delivered_schedules_recurrence(test_db):
    conn = reminder_service.get_db_connection(test_db)
    now_utc = to_utc_iso(datetime.now(timezone.utc))
    with conn:
        conn.execute(
            """
            INSERT INTO reminders (
                reminder_id, user_id, reminder_text, scheduled_utc,
                user_timezone, recurrence_rule, delivery_channel,
                recipient_id, status, retry_count, last_delivery_result,
                created_at, updated_at
            ) VALUES ('r-rec', 'default', 'Daily Standup', ?, 'Asia/Kolkata', 'daily', 'console', NULL, 'claimed', 0, NULL, ?, ?);
            """,
            (now_utc, now_utc, now_utc),
        )
    conn.close()

    reminder_service.mark_reminder_delivered(
        reminder_id="r-rec",
        delivery_result={"success": True},
        db_path=test_db,
    )

    # Original reminder is 'delivered'
    conn = reminder_service.get_db_connection(test_db)
    orig = conn.execute("SELECT status FROM reminders WHERE reminder_id = 'r-rec'").fetchone()
    assert orig["status"] == "delivered"

    # Next recurrence is spawned as 'pending'
    pending = conn.execute("SELECT * FROM reminders WHERE status = 'pending'").fetchall()
    assert len(pending) == 1
    assert pending[0]["reminder_text"] == "Daily Standup"
    assert pending[0]["recurrence_rule"] == "daily"
    conn.close()

    reminder_service.mark_reminder_delivered(
        reminder_id="r-rec",
        delivery_result={"success": True},
        db_path=test_db,
    )
    conn = reminder_service.get_db_connection(test_db)
    pending = conn.execute("SELECT * FROM reminders WHERE status = 'pending'").fetchall()
    conn.close()
    assert len(pending) == 1


def test_cancel_reminder_safeguard_and_execution(test_db):
    res_conf = reminder_service.create_reminder(
        reminder_text="Cancel Me",
        scheduled_time="tomorrow at 10 AM",
        confirmed=True,
        db_path=test_db,
    )
    rid = res_conf["reminder_id"]

    # Preview cancel
    res_prev = reminder_service.cancel_reminder(reminder_id=rid, confirmed=False, db_path=test_db)
    assert res_prev["requires_confirmation"] is True
    assert res_prev["cancelled"] is False

    # Confirmed cancel
    res_conf_cancel = reminder_service.cancel_reminder(reminder_id=rid, confirmed=True, db_path=test_db)
    assert res_conf_cancel["cancelled"] is True

    # Verify status is cancelled
    listed = reminder_service.list_reminders(status="all", db_path=test_db)
    assert listed["reminders"][0]["status"] == "cancelled"


def test_telegram_delivery_adapter_error_handling():
    # Missing token
    adapter_no_token = TelegramDeliveryAdapter(bot_token="", default_chat_id="12345")
    res = adapter_no_token.deliver("Test alert")
    assert res["success"] is False
    assert "token is not configured" in res["error"]

    # Missing chat ID
    adapter_no_chat = TelegramDeliveryAdapter(bot_token="fake-token", default_chat_id="")
    res = adapter_no_chat.deliver("Test alert")
    assert res["success"] is False
    assert "chat ID is not configured" in res["error"]


def test_delivery_adapter_rejects_unknown_channel():
    with pytest.raises(ValueError, match="Unsupported notification channel"):
        get_delivery_adapter("unsupported")


def test_telegram_error_does_not_expose_bot_token_from_exception():
    token = "private-bot-token"
    adapter = TelegramDeliveryAdapter(
        bot_token=token,
        default_chat_id="12345",
        max_retries=1,
    )
    with patch("httpx.post", side_effect=RuntimeError(f"/bot{token}/sendMessage")):
        result = adapter.deliver("Test alert")

    assert result["success"] is False
    assert "RuntimeError" in result["error"]
    assert token not in result["error"]


def test_telegram_delivery_adapter_success_and_retry():
    adapter = TelegramDeliveryAdapter(
        bot_token="mock-token",
        default_chat_id="12345",
        max_retries=2,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"result": {"message_id": 999}}

    with patch("httpx.post", return_value=mock_resp) as mock_post:
        res = adapter.deliver("Hello from test")

    assert res["success"] is True
    assert res["delivery_id"] == "999"
    mock_post.assert_called_once()


def test_console_delivery_adapter():
    adapter = ConsoleDeliveryAdapter()
    res = adapter.deliver("Console reminder test")
    assert res["success"] is True
    assert res["channel"] == "console"


def test_run_worker_tick_full_cycle(test_db):
    # Insert a due reminder
    past_due_utc = to_utc_iso(datetime.now(timezone.utc) - timedelta(minutes=2))
    conn = reminder_service.get_db_connection(test_db)
    with conn:
        conn.execute(
            """
            INSERT INTO reminders (
                reminder_id, user_id, reminder_text, scheduled_utc,
                user_timezone, recurrence_rule, delivery_channel,
                recipient_id, status, retry_count, last_delivery_result,
                created_at, updated_at
            ) VALUES ('r-tick-1', 'default', 'Tick Reminder', ?, 'Asia/Kolkata', NULL, 'console', NULL, 'pending', 0, NULL, ?, ?);
            """,
            (past_due_utc, past_due_utc, past_due_utc),
        )
    conn.close()

    # Run worker tick
    stats = reminder_worker.run_worker_tick(db_path=test_db)
    assert stats["claimed"] == 1
    assert stats["delivered"] == 1
    assert stats["failed"] == 0

    # Verify status in DB is delivered
    conn = reminder_service.get_db_connection(test_db)
    row = conn.execute("SELECT status FROM reminders WHERE reminder_id = 'r-tick-1'").fetchone()
    conn.close()
    assert row["status"] == "delivered"
