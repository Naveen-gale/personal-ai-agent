"""
services/reminder_service.py
----------------------------
Persistent SQLite-backed reminder engine supporting one-time and
recurring reminders, calendar-event relative reminders, atomic claims,
timezone handling (Asia/Kolkata default), and multi-channel notifications.
"""

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.services.date_utils import (
    DEFAULT_TIMEZONE_NAME,
    format_local_datetime,
    get_current_time,
    get_user_timezone,
    parse_datetime,
    to_utc_iso,
)

# Root directory for default database storage
_AGENT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path(os.getenv("REMINDERS_DB_PATH", str(_AGENT_DIR / "reminders.db")))


def get_db_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open or create a SQLite database connection with row factory and WAL mode."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Initialize the persistent reminders database schema."""
    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                reminder_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL DEFAULT 'default',
                reminder_text TEXT NOT NULL,
                scheduled_utc TEXT NOT NULL,
                user_timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
                recurrence_rule TEXT,
                delivery_channel TEXT NOT NULL DEFAULT 'telegram',
                recipient_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_delivery_result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reminders_status_sched
            ON reminders(status, scheduled_utc);
            """
        )
    conn.close()


def calculate_next_occurrence(
    current_utc_iso: str,
    recurrence_rule: str | None,
    tz_name: str = DEFAULT_TIMEZONE_NAME,
) -> str | None:
    """
    Calculate the next scheduled UTC ISO timestamp for a recurring reminder
    using the user's local timezone.
    """
    if not recurrence_rule or not recurrence_rule.strip():
        return None

    rule = _normalize_recurrence_rule(recurrence_rule)
    if rule is None:
        return None
    tz = get_user_timezone(tz_name)

    # Parse current scheduled time into local timezone
    dt_utc = datetime.fromisoformat(current_utc_iso.replace("Z", "+00:00"))
    local_dt = dt_utc.astimezone(tz)

    next_local = None

    if rule == "daily":
        next_local = local_dt + timedelta(days=1)
    elif rule == "weekly":
        next_local = local_dt + timedelta(days=7)
    elif rule.startswith("weekly:"):
        weekdays = (
            "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday",
        )
        target_weekday = weekdays.index(rule.partition(":")[2])
        days_ahead = (target_weekday - local_dt.weekday()) % 7 or 7
        next_local = local_dt + timedelta(days=days_ahead)
    elif rule.startswith("every_morning"):
        target_time = _recurrence_time(rule, "every_morning", time(9, 0))
        next_date = local_dt.date() + timedelta(days=1)
        next_local = datetime.combine(next_date, target_time, tzinfo=tz)
    else:
        target_time = _recurrence_time(rule, "every_evening", time(20, 0))
        next_date = local_dt.date() + timedelta(days=1)
        next_local = datetime.combine(next_date, target_time, tzinfo=tz)

    return to_utc_iso(next_local) if next_local else None


def _normalize_recurrence_rule(recurrence_rule: str | None) -> str | None:
    if recurrence_rule is None or not recurrence_rule.strip():
        return None

    rule = recurrence_rule.strip().casefold()
    if rule in {"daily", "weekly", "every_morning", "every_evening"}:
        return rule
    if re.fullmatch(
        r"weekly:(monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
        rule,
    ):
        return rule
    if re.fullmatch(r"every_morning:\d{1,2}:\d{2}", rule):
        _recurrence_time(rule, "every_morning", time(9, 0))
        return rule
    if re.fullmatch(r"every_evening:\d{1,2}:\d{2}", rule):
        _recurrence_time(rule, "every_evening", time(20, 0))
        return rule
    raise ValueError(
        "Unsupported recurrence rule. Use daily, weekly, weekly:<weekday>, "
        "every_morning[:HH:MM], or every_evening[:HH:MM]."
    )


def _recurrence_time(rule: str, prefix: str, default: time) -> time:
    if rule == prefix:
        return default
    _, _, value = rule.partition(":")
    hour, minute = value.split(":")
    try:
        return time(int(hour), int(minute))
    except ValueError as exc:
        raise ValueError(
            f"Invalid time in recurrence rule '{rule}'. Use a valid 24-hour HH:MM time."
        ) from exc


def create_reminder(
    reminder_text: str,
    scheduled_time: str,
    recurrence_rule: str | None = None,
    user_timezone: str = DEFAULT_TIMEZONE_NAME,
    delivery_channel: str = "telegram",
    recipient_id: str | None = None,
    confirmed: bool = False,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Create a one-time or recurring reminder with timezone awareness.
    Requires explicit user confirmation: previews details when confirmed=False.
    """
    text = (reminder_text or "").strip()
    if not text:
        raise ValueError("Reminder text cannot be empty.")

    recurrence_rule = _normalize_recurrence_rule(recurrence_rule)
    channel = (delivery_channel or "").strip().casefold()
    if channel not in {"telegram", "console"}:
        raise ValueError("Delivery channel must be either 'telegram' or 'console'.")
    delivery_channel = channel

    dt = parse_datetime(scheduled_time, tz_name=user_timezone)
    now = get_current_time(user_timezone)

    # Disallow scheduling in the past unless explicitly approved
    if dt < now - timedelta(minutes=1):
        raise ValueError(
            f"Scheduled time ({format_local_datetime(dt, tz_name=user_timezone)}) is in the past. "
            "Please specify a future time."
        )

    sched_utc = to_utc_iso(dt)
    local_display = format_local_datetime(dt, tz_name=user_timezone)

    preview = {
        "text": text,
        "scheduled_for": local_display,
        "scheduled_utc": sched_utc,
        "user_timezone": user_timezone,
        "recurrence": recurrence_rule or "None (One-time reminder)",
        "delivery_channel": delivery_channel,
    }

    if not confirmed:
        rec_desc = f" (Repeats: {recurrence_rule})" if recurrence_rule else ""
        return {
            "success": True,
            "created": False,
            "requires_confirmation": True,
            "preview": preview,
            "message": (
                f"Please confirm: Set reminder '{text}' for {local_display}{rec_desc} "
                f"via {delivery_channel}? (Type 'yes' to proceed)"
            ),
        }

    init_db(db_path)
    reminder_id = uuid.uuid4().hex
    now_utc = to_utc_iso(datetime.now(timezone.utc))

    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO reminders (
                reminder_id, user_id, reminder_text, scheduled_utc,
                user_timezone, recurrence_rule, delivery_channel,
                recipient_id, status, retry_count, last_delivery_result,
                created_at, updated_at
            ) VALUES (?, 'default', ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, ?, ?);
            """,
            (
                reminder_id,
                text,
                sched_utc,
                user_timezone,
                recurrence_rule.strip() if recurrence_rule else None,
                delivery_channel,
                recipient_id,
                now_utc,
                now_utc,
            ),
        )
    conn.close()

    return {
        "success": True,
        "created": True,
        "requires_confirmation": False,
        "reminder_id": reminder_id,
        "reminder": preview,
        "message": f"Reminder '{text}' scheduled for {local_display} successfully.",
    }


def list_reminders(
    status: str | None = "pending",
    limit: int = 20,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """List scheduled reminders from the persistent database."""
    init_db(db_path)
    conn = get_db_connection(db_path)

    query = "SELECT * FROM reminders"
    params: list[Any] = []
    if status and status != "all":
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY scheduled_utc ASC LIMIT ?"
    params.append(min(max(1, limit), 100))

    rows = conn.execute(query, params).fetchall()
    conn.close()

    reminders = []
    for r in rows:
        # Convert UTC ISO to local display
        try:
            dt_utc = datetime.fromisoformat(r["scheduled_utc"].replace("Z", "+00:00"))
            local_display = format_local_datetime(dt_utc, tz_name=r["user_timezone"])
        except Exception:
            local_display = r["scheduled_utc"]

        reminders.append(
            {
                "id": r["reminder_id"],
                "text": r["reminder_text"],
                "scheduled_utc": r["scheduled_utc"],
                "scheduled_display": local_display,
                "status": r["status"],
                "recurrence": r["recurrence_rule"] or "One-time",
                "channel": r["delivery_channel"],
                "retries": r["retry_count"],
            }
        )

    return {
        "success": True,
        "reminders": reminders,
        "count": len(reminders),
        "filter_status": status,
    }


def cancel_reminder(
    reminder_id: str,
    confirmed: bool = False,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """
    Cancel a pending reminder.
    Requires explicit user confirmation: previews before cancelling.
    """
    rid = (reminder_id or "").strip()
    if not rid:
        raise ValueError("Reminder ID is required.")

    init_db(db_path)
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT * FROM reminders WHERE reminder_id = ?", (rid,)).fetchone()

    if not row:
        conn.close()
        raise ValueError(f"Reminder with ID '{rid}' was not found.")

    if row["status"] in {"cancelled", "delivered"}:
        conn.close()
        return {
            "success": False,
            "message": f"Reminder '{row['reminder_text']}' is already {row['status']}.",
        }
    if row["status"] == "claimed":
        conn.close()
        return {
            "success": False,
            "cancelled": False,
            "message": "This reminder is already being delivered and cannot be cancelled.",
        }

    try:
        dt_utc = datetime.fromisoformat(row["scheduled_utc"].replace("Z", "+00:00"))
        local_display = format_local_datetime(dt_utc, tz_name=row["user_timezone"])
    except Exception:
        local_display = row["scheduled_utc"]

    if not confirmed:
        conn.close()
        return {
            "success": True,
            "cancelled": False,
            "requires_confirmation": True,
            "preview": {
                "id": rid,
                "text": row["reminder_text"],
                "scheduled": local_display,
            },
            "message": (
                f"Please confirm: Cancel reminder '{row['reminder_text']}' "
                f"scheduled for {local_display}? (Type 'yes' to proceed)"
            ),
        }

    now_utc = to_utc_iso(datetime.now(timezone.utc))
    with conn:
        conn.execute(
            "UPDATE reminders SET status = 'cancelled', updated_at = ? WHERE reminder_id = ?",
            (now_utc, rid),
        )
    conn.close()

    return {
        "success": True,
        "cancelled": True,
        "requires_confirmation": False,
        "message": f"Reminder '{row['reminder_text']}' cancelled successfully.",
    }


def claim_due_reminders(
    limit: int = 10,
    db_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    Atomically claim due reminders.
    Ensures that concurrency / multiple workers never deliver a reminder twice.
    """
    init_db(db_path)
    now_utc = to_utc_iso(datetime.now(timezone.utc))
    conn = get_db_connection(db_path)

    # 1. Find candidates that are pending and due
    candidates = conn.execute(
        """
        SELECT reminder_id, user_id, reminder_text, scheduled_utc,
               user_timezone, recurrence_rule, delivery_channel,
               recipient_id, retry_count
        FROM reminders
        WHERE status = 'pending' AND scheduled_utc <= ?
        ORDER BY scheduled_utc ASC
        LIMIT ?;
        """,
        (now_utc, limit),
    ).fetchall()

    claimed_reminders: list[dict[str, Any]] = []

    # 2. Atomically claim each candidate
    for cand in candidates:
        rid = cand["reminder_id"]
        cur = conn.cursor()
        with conn:
            cur.execute(
                """
                UPDATE reminders
                SET status = 'claimed', updated_at = ?
                WHERE reminder_id = ? AND status = 'pending';
                """,
                (now_utc, rid),
            )
            if cur.rowcount == 1:
                claimed_reminders.append(dict(cand))

    conn.close()
    return claimed_reminders


def recover_stale_claims(
    stale_minutes: int = 5,
    db_path: Path | str | None = None,
) -> int:
    """
    Reset reminders stuck in 'claimed' status (e.g. from an abrupt worker crash)
    back to 'pending' if updated_at is older than stale_minutes.
    """
    init_db(db_path)
    stale_threshold = to_utc_iso(datetime.now(timezone.utc) - timedelta(minutes=stale_minutes))
    now_utc = to_utc_iso(datetime.now(timezone.utc))

    conn = get_db_connection(db_path)
    with conn:
        cur = conn.execute(
            """
            UPDATE reminders
            SET status = 'pending', updated_at = ?
            WHERE status = 'claimed' AND updated_at < ? AND retry_count < 5;
            """,
            (now_utc, stale_threshold),
        )
        recovered_count = cur.rowcount
    conn.close()
    return recovered_count


def mark_reminder_delivered(
    reminder_id: str,
    delivery_result: dict[str, Any],
    db_path: Path | str | None = None,
) -> None:
    """Mark a claimed reminder as delivered and schedule next recurrence if recurring."""
    init_db(db_path)
    now_utc = to_utc_iso(datetime.now(timezone.utc))
    conn = get_db_connection(db_path)

    row = conn.execute("SELECT * FROM reminders WHERE reminder_id = ?", (reminder_id,)).fetchone()
    if not row:
        conn.close()
        return

    result_json = json.dumps(delivery_result)
    with conn:
        cur = conn.execute(
            """
            UPDATE reminders
            SET status = 'delivered', last_delivery_result = ?, updated_at = ?
            WHERE reminder_id = ? AND status = 'claimed';
            """,
            (result_json, now_utc, reminder_id),
        )

        # Handle recurrence: if rule is set, spawn next pending reminder
        if cur.rowcount == 1 and row["recurrence_rule"]:
            next_utc = calculate_next_occurrence(
                current_utc_iso=row["scheduled_utc"],
                recurrence_rule=row["recurrence_rule"],
                tz_name=row["user_timezone"],
            )
            if next_utc:
                new_id = uuid.uuid4().hex
                conn.execute(
                    """
                    INSERT INTO reminders (
                        reminder_id, user_id, reminder_text, scheduled_utc,
                        user_timezone, recurrence_rule, delivery_channel,
                        recipient_id, status, retry_count, last_delivery_result,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, ?, ?);
                    """,
                    (
                        new_id,
                        row["user_id"],
                        row["reminder_text"],
                        next_utc,
                        row["user_timezone"],
                        row["recurrence_rule"],
                        row["delivery_channel"],
                        row["recipient_id"],
                        now_utc,
                        now_utc,
                    ),
                )
    conn.close()


def mark_reminder_failed(
    reminder_id: str,
    error_message: str,
    max_retries: int = 3,
    db_path: Path | str | None = None,
) -> None:
    """Record delivery failure and either schedule retry with backoff or mark failed."""
    init_db(db_path)
    conn = get_db_connection(db_path)
    row = conn.execute("SELECT * FROM reminders WHERE reminder_id = ?", (reminder_id,)).fetchone()
    if not row:
        conn.close()
        return

    retries = row["retry_count"] + 1
    new_status = "failed" if retries >= max_retries else "pending"
    # Exponential backoff delay (e.g. 1 min, 2 min, 4 min) before re-attempting
    backoff_delay = timedelta(minutes=min(15, 2 ** (retries - 1)))
    next_attempt_utc = to_utc_iso(datetime.now(timezone.utc) + backoff_delay)
    now_utc = to_utc_iso(datetime.now(timezone.utc))

    with conn:
        conn.execute(
            """
            UPDATE reminders
            SET status = ?, retry_count = ?, scheduled_utc = ?,
                last_delivery_result = ?, updated_at = ?
            WHERE reminder_id = ? AND status = 'claimed';
            """,
            (new_status, retries, next_attempt_utc, error_message, now_utc, reminder_id),
        )
    conn.close()
