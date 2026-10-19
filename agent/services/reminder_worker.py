"""
services/reminder_worker.py
---------------------------
Standalone background worker process for delivering scheduled reminders.

Responsibilities:
  - Periodically poll for due reminders.
  - Concurrency-safe atomic claims to prevent concurrent worker delivery.
  - Deliver notifications via Telegram or Console.
  - Automatically calculate and schedule recurring occurrences.
  - Recover stale claims on worker restart.
  - Bounded exponential backoff on delivery failures.

Usage:
  python -m agent.services.reminder_worker
"""

import sys
import time
from pathlib import Path
from typing import Any

from agent.services.notification_service import get_delivery_adapter
from agent.services.reminder_service import (
    claim_due_reminders,
    mark_reminder_delivered,
    mark_reminder_failed,
    recover_stale_claims,
)


def run_worker_tick(db_path: Path | str | None = None) -> dict[str, Any]:
    """
    Execute a single worker cycle:
      1. Recover stale claims (> 5 minutes old).
      2. Atomically claim due reminders.
      3. Deliver each claimed reminder.
      4. Update database status.

    Returns:
        Summary dict of tick results.
    """
    stale_recovered = recover_stale_claims(stale_minutes=5, db_path=db_path)
    claimed = claim_due_reminders(limit=10, db_path=db_path)

    delivered_count = 0
    failed_count = 0

    for rem in claimed:
        channel = rem.get("delivery_channel", "telegram")
        try:
            adapter = get_delivery_adapter(channel)
        except ValueError as error:
            mark_reminder_failed(
                rem["reminder_id"], str(error), max_retries=3, db_path=db_path
            )
            failed_count += 1
            continue
        text = rem["reminder_text"]
        recipient = rem.get("recipient_id")

        result = adapter.deliver(text=text, recipient_id=recipient)
        if result.get("success"):
            mark_reminder_delivered(rem["reminder_id"], result, db_path=db_path)
            delivered_count += 1
        else:
            err = result.get("error", "Unknown delivery error")
            mark_reminder_failed(rem["reminder_id"], err, max_retries=3, db_path=db_path)
            failed_count += 1

    return {
        "stale_recovered": stale_recovered,
        "claimed": len(claimed),
        "delivered": delivered_count,
        "failed": failed_count,
    }


def start_worker(poll_interval: float = 10.0, db_path: Path | str | None = None) -> None:
    """Run the continuous reminder scheduler worker loop."""
    print("=" * 60)
    print("  Scheduled Reminders Background Worker")
    print("=" * 60)
    print(f"Polling interval: {poll_interval}s")
    print("Press Ctrl+C to stop the worker.")
    print("=" * 60)

    try:
        while True:
            stats = run_worker_tick(db_path=db_path)
            if stats["claimed"] > 0:
                print(
                    f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                    f"Processed {stats['claimed']} due reminders "
                    f"(Delivered: {stats['delivered']}, Failed: {stats['failed']})"
                )
            time.sleep(poll_interval)
    except (KeyboardInterrupt, SystemExit):
        print("\nReminder worker stopped.")


if __name__ == "__main__":
    interval = 10.0
    if len(sys.argv) > 1:
        try:
            interval = float(sys.argv[1])
        except ValueError:
            pass
    start_worker(poll_interval=interval)
