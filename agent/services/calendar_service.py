"""
services/calendar_service.py
----------------------------
Google Calendar API v3 service layer.

Responsibilities:
  - Authenticate with Google Calendar using the shared OAuth credentials.
  - List, search, and retrieve events with timezone awareness (Asia/Kolkata default).
  - Handle all-day events vs timed events.
  - Expand recurring events (singleEvents=True, orderBy=startTime).
  - Create, update, and delete events with strict confirmation safeguards.
  - Validate that start_time is before end_time.
  - Return clean, structured dictionaries.
"""

from collections.abc import Mapping
from datetime import datetime, time, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.auth.gmail_auth import CALENDAR_SCOPES, get_credentials
from agent.services.date_utils import (
    DEFAULT_TIMEZONE_NAME,
    format_local_datetime,
    get_current_time,
    get_user_timezone,
    parse_datetime,
    to_utc_iso,
)


def get_calendar_service() -> Any:
    """Build the Google Calendar API v3 client using OAuth credentials."""
    credentials = get_credentials(required_scopes=CALENDAR_SCOPES)
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _execute(request: Any) -> dict[str, Any]:
    """Execute a Google Calendar API request with clean error handling."""
    try:
        response = request.execute()
    except HttpError as error:
        status = getattr(error.resp, "status", "unknown")
        if status == 404:
            raise RuntimeError("Calendar event not found (404).") from error
        raise RuntimeError(
            f"Google Calendar API request failed (HTTP {status}). "
            "Check that the Google Calendar API is enabled and your OAuth token has calendar.events scope."
        ) from error
    except Exception as error:
        raise RuntimeError(
            f"Google Calendar API request failed ({type(error).__name__}). "
            "Check network connectivity and credentials."
        ) from error

    if not isinstance(response, Mapping):
        raise RuntimeError("Google Calendar API returned an invalid response.")
    return dict(response)


def _format_event(event: Mapping[str, Any], user_tz: str = DEFAULT_TIMEZONE_NAME) -> dict[str, Any]:
    """Convert raw Calendar API event resource into a clean, structured dictionary."""
    start_info = event.get("start", {})
    end_info = event.get("end", {})

    is_all_day = "date" in start_info and "dateTime" not in start_info
    start_str = start_info.get("dateTime") or start_info.get("date") or ""
    end_str = end_info.get("dateTime") or end_info.get("date") or ""

    # Parse formatted display strings
    start_display = start_str
    end_display = end_str
    if not is_all_day and start_str:
        try:
            st_dt = parse_datetime(start_str, tz_name=user_tz)
            start_display = format_local_datetime(st_dt, tz_name=user_tz)
        except Exception:
            start_display = start_str

    if not is_all_day and end_str:
        try:
            en_dt = parse_datetime(end_str, tz_name=user_tz)
            end_display = format_local_datetime(en_dt, tz_name=user_tz)
        except Exception:
            end_display = end_str

    # Extract meeting link if present (Google Meet or external)
    meeting_link = event.get("hangoutLink", "")
    if not meeting_link and "conferenceData" in event:
        entry_points = event["conferenceData"].get("entryPoints", [])
        for ep in entry_points:
            if ep.get("uri"):
                meeting_link = ep["uri"]
                break

    # Attendees summary
    attendees = [
        att.get("email")
        for att in event.get("attendees", [])
        if isinstance(att, Mapping) and att.get("email")
    ]

    return {
        "id": event.get("id", ""),
        "title": event.get("summary", "(No Title)"),
        "start": start_str,
        "end": end_str,
        "start_display": start_display,
        "end_display": end_display,
        "is_all_day": is_all_day,
        "time_zone": start_info.get("timeZone", user_tz),
        "location": event.get("location", ""),
        "description": event.get("description", ""),
        "meeting_link": meeting_link,
        "attendees": attendees,
        "status": event.get("status", "confirmed"),
        "html_link": event.get("htmlLink", ""),
    }


def list_calendar_events(
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    max_results: int = 10,
    time_zone: str = DEFAULT_TIMEZONE_NAME,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """
    List events from the primary calendar within an optional time range.
    Expands recurring events and sorts by start time.
    """
    service = get_calendar_service()
    params: dict[str, Any] = {
        "calendarId": calendar_id,
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": min(max(1, max_results), 50),
    }

    if start_time:
        if isinstance(start_time, str):
            st_dt = parse_datetime(start_time, tz_name=time_zone)
        else:
            st_dt = start_time
        params["timeMin"] = to_utc_iso(st_dt)

    if end_time:
        if isinstance(end_time, str):
            en_dt = parse_datetime(end_time, tz_name=time_zone)
        else:
            en_dt = end_time
        params["timeMax"] = to_utc_iso(en_dt)

    response = _execute(service.events().list(**params))
    items = response.get("items", [])
    events = [
        _format_event(item, user_tz=time_zone)
        for item in items
        if item.get("status") != "cancelled"
    ]

    return {
        "success": True,
        "events": events,
        "count": len(events),
        "time_zone": time_zone,
    }


def get_today_events(time_zone: str = DEFAULT_TIMEZONE_NAME) -> dict[str, Any]:
    """Retrieve all calendar events for today in the user's timezone."""
    now = get_current_time(time_zone)
    today_start = datetime.combine(now.date(), time(0, 0, 0), tzinfo=now.tzinfo)
    today_end = datetime.combine(now.date(), time(23, 59, 59), tzinfo=now.tzinfo)
    return list_calendar_events(
        start_time=today_start,
        end_time=today_end,
        max_results=20,
        time_zone=time_zone,
    )


def get_upcoming_events(
    max_results: int = 10, time_zone: str = DEFAULT_TIMEZONE_NAME
) -> dict[str, Any]:
    """Retrieve upcoming events from current time onwards."""
    now = get_current_time(time_zone)
    return list_calendar_events(
        start_time=now,
        max_results=max_results,
        time_zone=time_zone,
    )


def search_calendar_events(
    query: str,
    max_results: int = 10,
    time_zone: str = DEFAULT_TIMEZONE_NAME,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """Search events by keyword matching title, description, or attendees."""
    q_clean = query.strip() if isinstance(query, str) else ""
    if not q_clean:
        return {"success": True, "events": [], "count": 0, "message": "Search query cannot be empty."}

    service = get_calendar_service()
    params: dict[str, Any] = {
        "calendarId": calendar_id,
        "q": q_clean,
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": min(max(1, max_results), 50),
    }

    response = _execute(service.events().list(**params))
    items = response.get("items", [])
    events = [
        _format_event(item, user_tz=time_zone)
        for item in items
        if item.get("status") != "cancelled"
    ]

    return {
        "success": True,
        "query": q_clean,
        "events": events,
        "count": len(events),
        "time_zone": time_zone,
    }


def get_event_details(event_id: str, calendar_id: str = "primary") -> dict[str, Any]:
    """Retrieve detailed information for a specific event by ID."""
    if not event_id or not str(event_id).strip():
        raise ValueError("Event ID is required.")

    service = get_calendar_service()
    event_data = _execute(service.events().get(calendarId=calendar_id, eventId=event_id.strip()))
    formatted = _format_event(event_data)
    return {"success": True, "event": formatted}


def create_calendar_event(
    title: str,
    start_time: str,
    end_time: str | None = None,
    duration_minutes: int = 30,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    time_zone: str = DEFAULT_TIMEZONE_NAME,
    calendar_id: str = "primary",
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Create a new calendar event.
    Requires explicit confirmation: returns preview when confirmed=False.
    """
    t_clean = (title or "").strip()
    if not t_clean:
        raise ValueError("Event title is required.")

    st_dt = parse_datetime(start_time, tz_name=time_zone)
    if end_time:
        en_dt = parse_datetime(end_time, tz_name=time_zone)
    else:
        en_dt = st_dt + timedelta(minutes=max(1, duration_minutes))

    if en_dt <= st_dt:
        raise ValueError(f"Event end time ({en_dt}) must be strictly after start time ({st_dt}).")

    preview = {
        "title": t_clean,
        "start": format_local_datetime(st_dt, tz_name=time_zone),
        "end": format_local_datetime(en_dt, tz_name=time_zone),
        "start_iso": to_utc_iso(st_dt),
        "end_iso": to_utc_iso(en_dt),
        "time_zone": time_zone,
        "description": description.strip(),
        "location": location.strip(),
        "attendees": [a.strip() for a in (attendees or []) if a.strip()],
    }

    if not confirmed:
        return {
            "success": True,
            "created": False,
            "requires_confirmation": True,
            "preview": preview,
            "message": (
                f"Please confirm: Create calendar event '{t_clean}' "
                f"from {preview['start']} to {preview['end']}? (Type 'yes' to proceed)"
            ),
        }

    # Construct Calendar API event body
    event_body: dict[str, Any] = {
        "summary": t_clean,
        "start": {
            "dateTime": to_utc_iso(st_dt),
            "timeZone": time_zone,
        },
        "end": {
            "dateTime": to_utc_iso(en_dt),
            "timeZone": time_zone,
        },
    }
    if description.strip():
        event_body["description"] = description.strip()
    if location.strip():
        event_body["location"] = location.strip()
    if attendees:
        event_body["attendees"] = [{"email": a.strip()} for a in attendees if a.strip()]

    service = get_calendar_service()
    created = _execute(service.events().insert(calendarId=calendar_id, body=event_body))
    formatted = _format_event(created, user_tz=time_zone)

    return {
        "success": True,
        "created": True,
        "requires_confirmation": False,
        "event": formatted,
        "message": f"Calendar event '{t_clean}' scheduled successfully.",
    }


def update_calendar_event(
    event_id: str,
    title: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    location: str | None = None,
    time_zone: str = DEFAULT_TIMEZONE_NAME,
    calendar_id: str = "primary",
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Update an existing calendar event.
    Requires explicit confirmation: previews changes before applying.
    """
    eid = (event_id or "").strip()
    if not eid:
        raise ValueError("Event ID is required to update an event.")

    service = get_calendar_service()
    existing_raw = _execute(service.events().get(calendarId=calendar_id, eventId=eid))
    existing = _format_event(existing_raw, user_tz=time_zone)

    # Determine proposed changes
    patch_body: dict[str, Any] = {}
    preview_changes: dict[str, Any] = {"id": eid, "current_title": existing["title"]}

    if title is not None and title.strip():
        patch_body["summary"] = title.strip()
        preview_changes["new_title"] = title.strip()

    st_dt = None
    if start_time:
        st_dt = parse_datetime(start_time, tz_name=time_zone)
        patch_body["start"] = {"dateTime": to_utc_iso(st_dt), "timeZone": time_zone}
        preview_changes["new_start"] = format_local_datetime(st_dt, tz_name=time_zone)

    if end_time:
        en_dt = parse_datetime(end_time, tz_name=time_zone)
        patch_body["end"] = {"dateTime": to_utc_iso(en_dt), "timeZone": time_zone}
        preview_changes["new_end"] = format_local_datetime(en_dt, tz_name=time_zone)

    # Validate that new start is before new end if both/either changed
    if start_time or end_time:
        eff_start = st_dt or parse_datetime(existing["start"], tz_name=time_zone)
        eff_end = (
            parse_datetime(end_time, tz_name=time_zone)
            if end_time
            else parse_datetime(existing["end"], tz_name=time_zone)
        )
        if eff_end <= eff_start:
            raise ValueError(f"Updated end time ({eff_end}) must be after start time ({eff_start}).")

    if description is not None:
        patch_body["description"] = description.strip()
        preview_changes["new_description"] = description.strip()

    if location is not None:
        patch_body["location"] = location.strip()
        preview_changes["new_location"] = location.strip()

    if not patch_body:
        return {"success": True, "updated": False, "message": "No changes specified."}

    if not confirmed:
        return {
            "success": True,
            "updated": False,
            "requires_confirmation": True,
            "preview": preview_changes,
            "message": (
                f"Please confirm: Update event '{existing['title']}' with these changes? "
                f"(Type 'yes' to proceed)"
            ),
        }

    updated = _execute(
        service.events().patch(calendarId=calendar_id, eventId=eid, body=patch_body)
    )
    formatted = _format_event(updated, user_tz=time_zone)

    return {
        "success": True,
        "updated": True,
        "requires_confirmation": False,
        "event": formatted,
        "message": f"Calendar event '{formatted['title']}' updated successfully.",
    }


def delete_calendar_event(
    event_id: str,
    calendar_id: str = "primary",
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Delete a calendar event by ID.
    Requires explicit confirmation: previews event details before deleting.
    """
    eid = (event_id or "").strip()
    if not eid:
        raise ValueError("Event ID is required to delete an event.")

    service = get_calendar_service()
    existing_raw = _execute(service.events().get(calendarId=calendar_id, eventId=eid))
    existing = _format_event(existing_raw)

    if not confirmed:
        return {
            "success": True,
            "deleted": False,
            "requires_confirmation": True,
            "preview": {
                "id": eid,
                "title": existing["title"],
                "start": existing["start_display"],
                "end": existing["end_display"],
            },
            "message": (
                f"Please confirm: Cancel/delete event '{existing['title']}' "
                f"scheduled for {existing['start_display']}? (Type 'yes' to proceed)"
            ),
        }

    try:
        service.events().delete(calendarId=calendar_id, eventId=eid).execute()
    except Exception as error:
        raise RuntimeError(f"Failed to delete calendar event ({type(error).__name__}).") from error

    return {
        "success": True,
        "deleted": True,
        "requires_confirmation": False,
        "message": f"Calendar event '{existing['title']}' has been removed from your calendar.",
    }

