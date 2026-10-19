"""
tests/test_calendar.py
----------------------
Unit tests for Google Calendar service, operations, and safeguards.
External Google Calendar API calls are fully mocked.
"""

from unittest.mock import MagicMock, patch
import pytest

from agent.auth.gmail_auth import CALENDAR_SCOPES
from agent.services import calendar_service


def test_calendar_scopes_defined_and_correct():
    assert "https://www.googleapis.com/auth/calendar.events" in CALENDAR_SCOPES


def test_get_calendar_service_uses_calendar_scopes():
    mock_creds = MagicMock()
    mock_service = MagicMock()

    with patch(
        "agent.services.calendar_service.get_credentials",
        return_value=mock_creds,
    ) as mock_get_creds, patch(
        "agent.services.calendar_service.build",
        return_value=mock_service,
    ) as mock_build:
        svc = calendar_service.get_calendar_service()

    assert svc is mock_service
    mock_get_creds.assert_called_once_with(required_scopes=CALENDAR_SCOPES)
    mock_build.assert_called_once_with("calendar", "v3", credentials=mock_creds, cache_discovery=False)


def test_list_calendar_events_formats_timed_and_all_day_events():
    mock_service = MagicMock()
    mock_events_api = mock_service.events.return_value
    mock_list_req = mock_events_api.list.return_value

    mock_list_req.execute.return_value = {
        "items": [
            {
                "id": "event-1",
                "summary": "Team Standup",
                "status": "confirmed",
                "start": {"dateTime": "2026-10-20T10:00:00+05:30", "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": "2026-10-20T10:30:00+05:30", "timeZone": "Asia/Kolkata"},
                "location": "Room 402",
                "hangoutLink": "https://meet.google.com/abc-defg-hij",
            },
            {
                "id": "event-2",
                "summary": "Company Holiday",
                "status": "confirmed",
                "start": {"date": "2026-10-21"},
                "end": {"date": "2026-10-22"},
            },
            {
                "id": "event-cancelled",
                "summary": "Cancelled Meet",
                "status": "cancelled",
                "start": {"dateTime": "2026-10-20T15:00:00+05:30"},
                "end": {"dateTime": "2026-10-20T16:00:00+05:30"},
            },
        ]
    }

    with patch("agent.services.calendar_service.get_calendar_service", return_value=mock_service):
        res = calendar_service.list_calendar_events()

    assert res["success"] is True
    assert res["count"] == 2  # Cancelled event excluded
    events = res["events"]

    # Timed event
    assert events[0]["id"] == "event-1"
    assert events[0]["title"] == "Team Standup"
    assert events[0]["is_all_day"] is False
    assert events[0]["meeting_link"] == "https://meet.google.com/abc-defg-hij"

    # All-day event
    assert events[1]["id"] == "event-2"
    assert events[1]["title"] == "Company Holiday"
    assert events[1]["is_all_day"] is True


def test_get_today_events_calculates_today_range():
    mock_service = MagicMock()
    mock_list_req = mock_service.events.return_value.list.return_value
    mock_list_req.execute.return_value = {"items": []}

    with patch("agent.services.calendar_service.get_calendar_service", return_value=mock_service):
        res = calendar_service.get_today_events(time_zone="Asia/Kolkata")

    assert res["success"] is True
    assert res["count"] == 0
    call_kwargs = mock_service.events.return_value.list.call_args[1]
    assert "timeMin" in call_kwargs
    assert "timeMax" in call_kwargs
    assert call_kwargs["singleEvents"] is True
    assert call_kwargs["orderBy"] == "startTime"


def test_create_calendar_event_requires_confirmation_preview():
    # Calling with confirmed=False must NOT call Google Calendar API
    with patch("agent.services.calendar_service.get_calendar_service") as mock_get_svc:
        res = calendar_service.create_calendar_event(
            title="Design Review",
            start_time="2026-10-20 14:00",
            duration_minutes=45,
            confirmed=False,
        )

    mock_get_svc.assert_not_called()
    assert res["success"] is True
    assert res["created"] is False
    assert res["requires_confirmation"] is True
    assert res["preview"]["title"] == "Design Review"
    assert "Please confirm" in res["message"]


def test_create_calendar_event_executes_when_confirmed():
    mock_service = MagicMock()
    mock_insert_req = mock_service.events.return_value.insert.return_value
    mock_insert_req.execute.return_value = {
        "id": "new-evt-123",
        "summary": "Design Review",
        "status": "confirmed",
        "start": {"dateTime": "2026-10-20T14:00:00+05:30"},
        "end": {"dateTime": "2026-10-20T14:45:00+05:30"},
    }

    with patch("agent.services.calendar_service.get_calendar_service", return_value=mock_service):
        res = calendar_service.create_calendar_event(
            title="Design Review",
            start_time="2026-10-20 14:00",
            duration_minutes=45,
            confirmed=True,
        )

    assert res["success"] is True
    assert res["created"] is True
    assert res["requires_confirmation"] is False
    assert res["event"]["id"] == "new-evt-123"
    assert res["event"]["title"] == "Design Review"


def test_create_calendar_event_rejects_invalid_times():
    with pytest.raises(ValueError, match="strictly after start time"):
        calendar_service.create_calendar_event(
            title="Invalid Event",
            start_time="2026-10-20 15:00",
            end_time="2026-10-20 14:00",
            confirmed=False,
        )


def test_update_calendar_event_safeguard_and_execution():
    mock_service = MagicMock()
    mock_events = mock_service.events.return_value
    mock_events.get.return_value.execute.return_value = {
        "id": "evt-update",
        "summary": "Old Title",
        "start": {"dateTime": "2026-10-20T10:00:00+05:30"},
        "end": {"dateTime": "2026-10-20T11:00:00+05:30"},
    }

    # Step 1: Preview without confirmation
    with patch("agent.services.calendar_service.get_calendar_service", return_value=mock_service):
        res_preview = calendar_service.update_calendar_event(
            event_id="evt-update",
            title="New Title",
            confirmed=False,
        )

    assert res_preview["requires_confirmation"] is True
    assert res_preview["updated"] is False
    assert res_preview["preview"]["new_title"] == "New Title"
    mock_events.patch.assert_not_called()

    # Step 2: Confirmed update executes patch
    mock_events.patch.return_value.execute.return_value = {
        "id": "evt-update",
        "summary": "New Title",
        "start": {"dateTime": "2026-10-20T10:00:00+05:30"},
        "end": {"dateTime": "2026-10-20T11:00:00+05:30"},
    }
    with patch("agent.services.calendar_service.get_calendar_service", return_value=mock_service):
        res_confirmed = calendar_service.update_calendar_event(
            event_id="evt-update",
            title="New Title",
            confirmed=True,
        )

    assert res_confirmed["updated"] is True
    assert res_confirmed["event"]["title"] == "New Title"


def test_delete_calendar_event_safeguard_and_execution():
    mock_service = MagicMock()
    mock_events = mock_service.events.return_value
    mock_events.get.return_value.execute.return_value = {
        "id": "evt-del",
        "summary": "Cancel Me",
        "start": {"dateTime": "2026-10-20T10:00:00+05:30"},
        "end": {"dateTime": "2026-10-20T11:00:00+05:30"},
    }

    # Preview
    with patch("agent.services.calendar_service.get_calendar_service", return_value=mock_service):
        res_preview = calendar_service.delete_calendar_event(event_id="evt-del", confirmed=False)

    assert res_preview["requires_confirmation"] is True
    assert res_preview["deleted"] is False
    mock_events.delete.assert_not_called()

    # Confirmed execution
    mock_events.delete.return_value.execute.return_value = {}
    with patch("agent.services.calendar_service.get_calendar_service", return_value=mock_service):
        res_confirmed = calendar_service.delete_calendar_event(event_id="evt-del", confirmed=True)

    assert res_confirmed["deleted"] is True
    mock_events.delete.assert_called_once_with(calendarId="primary", eventId="evt-del")

