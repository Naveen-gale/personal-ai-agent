"""
services/date_utils.py
----------------------
Timezone-aware date and time parsing utilities for Google Calendar,
Google Tasks, and Scheduled Reminders.

Default timezone: Asia/Kolkata (IST, UTC+05:30)
"""

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import dateutil.parser

DEFAULT_TIMEZONE_NAME = os.getenv("USER_TIMEZONE", "Asia/Kolkata")


def get_user_timezone(tz_name: str | None = None) -> ZoneInfo:
    """Return the configured IANA timezone or raise for an invalid timezone."""
    name = DEFAULT_TIMEZONE_NAME if tz_name is None else tz_name.strip()
    if not name:
        raise ValueError("Timezone cannot be empty.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(
            f"Unknown timezone '{name}'. Use a valid IANA timezone such as "
            "'Asia/Kolkata' or 'America/New_York'."
        ) from exc


def get_current_time(tz_name: str | None = None) -> datetime:
    """Return the current timezone-aware datetime in the user's timezone."""
    tz = get_user_timezone(tz_name)
    return datetime.now(tz)


def to_utc_iso(dt: datetime) -> str:
    """Convert any datetime to a UTC ISO 8601 string (e.g. 2026-10-19T05:00:00Z)."""
    if dt.tzinfo is None:
        tz = get_user_timezone()
        dt = dt.replace(tzinfo=tz)
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_datetime(
    text: str,
    tz_name: str | None = None,
    default_time: time | None = None,
) -> datetime:
    """
    Parse a natural-language or ISO datetime string into a timezone-aware datetime.

    Supports:
      - Relative: "in 30 minutes", "in 2 hours", "in 1 day"
      - Day words: "today", "tomorrow", "day after tomorrow"
      - Weekdays: "next Monday", "this Friday", "Saturday"
      - Times: "at 10 AM", "7:30 PM", "15:00"
      - ISO / standard strings: "2026-10-20T14:00:00", "2026-10-20"

    Raises:
        ValueError: If text cannot be parsed or is empty.
    """
    if not text or not str(text).strip():
        raise ValueError("Datetime string cannot be empty.")

    cleaned = str(text).strip()
    tz = get_user_timezone(tz_name)
    now = datetime.now(tz)
    # Default baseline with zeroed minutes/seconds for clean time parsing
    midnight_default = datetime.combine(now.date(), time(0, 0, 0), tzinfo=tz)

    # 1. Check relative "in X minutes / hours / days / seconds"
    rel_match = re.fullmatch(
        r"in\s+(\d+(?:\.\d+)?)\s*(minutes?|mins?|hours?|hrs?|days?|secs?|seconds?)",
        cleaned,
        re.IGNORECASE,
    )
    if rel_match:
        val = float(rel_match.group(1))
        unit = rel_match.group(2).lower()
        if "min" in unit:
            return now + timedelta(minutes=val)
        if "hour" in unit or "hr" in unit:
            return now + timedelta(hours=val)
        if "day" in unit:
            return now + timedelta(days=val)
        if "sec" in unit:
            return now + timedelta(seconds=val)

    # 2. Check "today", "tomorrow", "day after tomorrow" with optional time
    day_match = re.match(
        r"^(today|tomorrow|day after tomorrow)(?:\s+(?:at\s+)?(.*))?$",
        cleaned,
        re.IGNORECASE,
    )
    if day_match:
        day_word = day_match.group(1).lower()
        time_part = (day_match.group(2) or "").strip()

        base_date = now.date()
        if day_word == "tomorrow":
            base_date += timedelta(days=1)
        elif day_word == "day after tomorrow":
            base_date += timedelta(days=2)

        if time_part:
            parsed_time = dateutil.parser.parse(time_part, default=midnight_default).time()
        else:
            parsed_time = default_time or time(9, 0)  # default 9:00 AM

        return datetime.combine(base_date, parsed_time, tzinfo=tz)

    # 3. Check weekday names e.g. "next monday at 2 PM", "friday 10am"
    weekday_match = re.match(
        r"^(?:next\s+|this\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(?:at\s+)?(.*))?$",
        cleaned,
        re.IGNORECASE,
    )
    if weekday_match:
        target_name = weekday_match.group(1).lower()
        time_part = (weekday_match.group(2) or "").strip()
        weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        target_idx = weekdays.index(target_name)
        current_idx = now.weekday()

        days_ahead = (target_idx - current_idx) % 7
        if days_ahead == 0 and "next" in cleaned.lower():
            days_ahead = 7
        elif days_ahead == 0 and not time_part:
            days_ahead = 7 if "next" in cleaned.lower() else 0

        target_date = now.date() + timedelta(days=days_ahead)
        if time_part:
            parsed_time = dateutil.parser.parse(time_part, default=midnight_default).time()
        else:
            parsed_time = default_time or time(9, 0)
        return datetime.combine(target_date, parsed_time, tzinfo=tz)

    # 4. Standard parsing via dateutil with clean defaults
    try:
        parsed = dateutil.parser.parse(cleaned, default=midnight_default)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        else:
            parsed = parsed.astimezone(tz)
        return parsed
    except Exception as exc:
        raise ValueError(
            f"Could not parse date/time '{text}'. Please provide a clear format like "
            "'2026-10-20 14:00', 'tomorrow at 10 AM', or 'in 30 minutes'."
        ) from exc


def format_local_datetime(dt: datetime, tz_name: str | None = None) -> str:
    """Format a datetime into a human-friendly string in the user's timezone."""
    tz = get_user_timezone(tz_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local_dt = dt.astimezone(tz)
    return local_dt.strftime("%A, %B %d, %Y at %I:%M %p %Z")


def parse_date_only_due(due_text: str, tz_name: str | None = None) -> str:
    """
    Format a date into an RFC 3339 timestamp formatted for Google Tasks due dates.

    Google Tasks API requires `due` to be an RFC 3339 formatted timestamp,
    e.g. 2026-10-20T00:00:00.000Z.
    """
    dt = parse_datetime(due_text, tz_name=tz_name, default_time=time(0, 0))
    # Tasks due date is saved in UTC with 00:00:00.000Z
    return dt.strftime("%Y-%m-%dT00:00:00.000Z")
