"""
tools/calendar_tools.py
-----------------------
LangChain tools for Google Calendar.
Docstrings are concise to maintain a low token footprint on Groq.
"""

from typing import Any
from langchain_core.tools import tool
from agent.tools.confirmation import consume_tool_authorization

from agent.services.calendar_service import (
    create_calendar_event as create_calendar_event_service,
    delete_calendar_event as delete_calendar_event_service,
    get_today_events as get_today_events_service,
    list_calendar_events as list_calendar_events_service,
    search_calendar_events as search_calendar_events_service,
    update_calendar_event as update_calendar_event_service,
)


@tool
def get_today_events(time_zone: str = "Asia/Kolkata") -> dict:
    """Retrieve all Google Calendar events scheduled for today in the user's timezone."""
    try:
        return get_today_events_service(time_zone=time_zone)
    except Exception as error:
        return {"success": False, "events": [], "count": 0, "message": f"Failed to get today's events: {error}"}


@tool
def list_calendar_events(
    start_time: str = "",
    end_time: str = "",
    max_results: int = 10,
    time_zone: str = "Asia/Kolkata",
) -> dict:
    """List Google Calendar events within an optional time range (e.g. tomorrow, next week)."""
    try:
        return list_calendar_events_service(
            start_time=start_time or None,
            end_time=end_time or None,
            max_results=max_results,
            time_zone=time_zone,
        )
    except Exception as error:
        return {"success": False, "events": [], "count": 0, "message": f"Failed to list events: {error}"}


@tool
def search_calendar_events(
    query: str,
    max_results: int = 10,
    time_zone: str = "Asia/Kolkata",
) -> dict:
    """Search Google Calendar events by keyword matching title, description, or attendees."""
    try:
        return search_calendar_events_service(query=query, max_results=max_results, time_zone=time_zone)
    except Exception as error:
        return {"success": False, "events": [], "count": 0, "message": f"Search failed: {error}"}


@tool
def create_calendar_event(
    title: str,
    start_time: str,
    end_time: str = "",
    duration_minutes: int = 30,
    description: str = "",
    location: str = "",
    confirmed: bool = False,
    time_zone: str = "Asia/Kolkata",
) -> dict:
    """Preview event when confirmed=False; schedule to calendar only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("create_calendar_event")
        return create_calendar_event_service(
            title=title,
            start_time=start_time,
            end_time=end_time or None,
            duration_minutes=duration_minutes,
            description=description,
            location=location,
            time_zone=time_zone,
            confirmed=confirmed,
        )
    except Exception as error:
        return {
            "success": False,
            "created": False,
            "requires_confirmation": False,
            "message": f"Could not create event: {error}",
        }


@tool
def update_calendar_event(
    event_id: str,
    title: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
    location: str = "",
    confirmed: bool = False,
    time_zone: str = "Asia/Kolkata",
) -> dict:
    """Preview event update when confirmed=False; apply patch only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("update_calendar_event")
        return update_calendar_event_service(
            event_id=event_id,
            title=title or None,
            start_time=start_time or None,
            end_time=end_time or None,
            description=description or None,
            location=location or None,
            time_zone=time_zone,
            confirmed=confirmed,
        )
    except Exception as error:
        return {
            "success": False,
            "updated": False,
            "requires_confirmation": False,
            "message": f"Could not update event: {error}",
        }


@tool
def delete_calendar_event(event_id: str, confirmed: bool = False) -> dict:
    """Preview event deletion when confirmed=False; delete event only when confirmed=True after user approves."""
    try:
        confirmed = confirmed and consume_tool_authorization("delete_calendar_event")
        return delete_calendar_event_service(event_id=event_id, confirmed=confirmed)
    except Exception as error:
        return {
            "success": False,
            "deleted": False,
            "requires_confirmation": False,
            "message": f"Could not delete event: {error}",
        }


CALENDAR_TOOLS = [
    get_today_events,
    list_calendar_events,
    search_calendar_events,
    create_calendar_event,
    update_calendar_event,
    delete_calendar_event,
]
