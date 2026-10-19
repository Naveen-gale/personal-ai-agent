"""
tools/assistant_tools.py
-------------------------
General-purpose tools for the assistant.

Place tools here that are genuinely useful across many types of requests
and are NOT specific to a single integration (like Gmail).

Rules:
  - Each tool must have a clear name and a docstring.
  - Each tool must return real, accurate information.
  - Do not include fake demonstration tools.
"""

from datetime import datetime, timezone

from langchain_core.tools import tool

from agent.services.date_utils import get_user_timezone


@tool
def get_current_datetime() -> str:
    """Return the current date and time in local timezone (Asia/Kolkata) and UTC."""
    now_utc = datetime.now(tz=timezone.utc)
    tz_local = get_user_timezone()
    now_local = now_utc.astimezone(tz_local)
    return (
        f"Current local time (Asia/Kolkata): {now_local.strftime('%A, %B %d, %Y at %I:%M:%S %p %Z')} | "
        f"UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"
    )
