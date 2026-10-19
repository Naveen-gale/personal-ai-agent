"""Mocked Google People API tests for contact search."""

from unittest.mock import MagicMock, patch

import pytest

from agent.services import contacts_service


def person(resource_name="people/1", display_name="Alex Morgan", phone="+1 (555) 123-4567"):
    return {
        "resourceName": resource_name,
        "names": [{"displayName": display_name}],
        "phoneNumbers": [{"value": phone}],
        "emailAddresses": [{"value": "alex@example.test"}],
    }


def mock_contacts_service():
    service = MagicMock()
    return service


@pytest.mark.parametrize(
    "query",
    ["Alex Morgan", "Alex", "Morgan", "Taylor", "Anne-Marie"],
)
def test_name_queries_use_people_search_and_format_contact(query):
    service = mock_contacts_service()
    search = service.people().searchContacts
    search.return_value.execute.side_effect = [
        {"results": []},
        {"results": [{"person": person(display_name="Alex Taylor Morgan")}]},
    ]

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        result = contacts_service.search_contacts(query)

    assert result["success"] is True
    assert result["count"] == 1
    assert result["matches"][0] == {
        "name": "Alex Taylor Morgan",
        "phone_numbers": ["+1 (555) 123-4567"],
        "emails": ["alex@example.test"],
    }
    assert search.call_args_list[0].kwargs["query"] == ""
    assert search.call_args_list[1].kwargs["query"] == query
    assert search.call_args_list[0].kwargs["readMask"] == contacts_service.CONTACT_FIELDS


@pytest.mark.parametrize(
    "query",
    ["1555", "123", "4567"],
)
def test_phone_search_matches_leading_middle_and_trailing_digits(query):
    service = mock_contacts_service()
    service.people().connections().list.return_value.execute.return_value = {
        "connections": [person()]
    }

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        result = contacts_service.search_contacts(query)

    assert result["count"] == 1
    assert result["matches"][0]["name"] == "Alex Morgan"


def test_phone_search_follows_all_connection_pages_and_deduplicates():
    service = mock_contacts_service()
    list_request = service.people().connections().list.return_value
    list_request.execute.side_effect = [
        {"connections": [person()], "nextPageToken": "page-2"},
        {"connections": [person(), person("people/2", "Other Person")]},
    ]

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        result = contacts_service.search_contacts("123")

    assert [contact["name"] for contact in result["matches"]] == [
        "Alex Morgan",
        "Other Person",
    ]
    assert service.people().connections().list.call_count == 2
    assert service.people().connections().list.call_args_list[1].kwargs["pageToken"] == "page-2"


def test_name_search_follows_pages_and_deduplicates_results():
    service = mock_contacts_service()
    service.people().searchContacts.return_value.execute.side_effect = [
        {"results": []},
        {
            "results": [{"person": person()}],
            "nextPageToken": "search-page-2",
        },
        {"results": [{"person": person()}, {"person": person("people/2", "Other Person")}]},
    ]

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        result = contacts_service.search_contacts("Alex")

    assert [contact["name"] for contact in result["matches"]] == [
        "Alex Morgan",
        "Other Person",
    ]
    assert service.people().searchContacts.call_count == 3
    assert (
        service.people().searchContacts.call_args_list[2].kwargs["pageToken"]
        == "search-page-2"
    )


def test_empty_query_does_not_call_api_or_match_every_phone():
    with patch.object(contacts_service, "get_contacts_service") as get_service:
        result = contacts_service.search_contacts("   ")

    assert result == {
        "success": True,
        "matches": [],
        "count": 0,
        "message": "Enter a name or phone digits.",
    }
    get_service.assert_not_called()


def test_no_match_result_is_explicit():
    service = mock_contacts_service()
    service.people().searchContacts.return_value.execute.side_effect = [
        {"results": []},
        {"results": []},
    ]

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        result = contacts_service.search_contacts("no such contact")

    assert result["success"] is True
    assert result["matches"] == []
    assert result["message"] == "No matching contacts found."


def test_phone_query_with_no_digits_does_not_search():
    with patch.object(contacts_service, "get_contacts_service") as get_service:
        result = contacts_service.search_contacts("()+-. ")

    assert result["count"] == 0
    get_service.assert_not_called()


def test_invalid_limit_is_rejected():
    with pytest.raises(ValueError, match="positive integer"):
        contacts_service.search_contacts("Alex", limit=0)


def test_malformed_api_response_is_reported():
    service = mock_contacts_service()
    service.people().searchContacts.return_value.execute.side_effect = [
        [],
    ]

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        with pytest.raises(RuntimeError, match="invalid response"):
            contacts_service.search_contacts("Alex")


def test_api_error_does_not_expose_response_body():
    from googleapiclient.errors import HttpError

    response = MagicMock()
    response.status = 403
    error = HttpError(response, b"private contact data")
    with pytest.raises(RuntimeError, match="HTTP 403") as caught:
        contacts_service._execute(MagicMock(execute=MagicMock(side_effect=error)))

    assert "private contact data" not in str(caught.value)
