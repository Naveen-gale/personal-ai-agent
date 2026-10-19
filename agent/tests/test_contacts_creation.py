"""Mocked Google People API tests for safe contact creation."""

from unittest.mock import MagicMock, patch

import pytest

from agent.services import contacts_service


def test_contact_creation_requires_name_and_phone():
    with pytest.raises(ValueError, match="name is required"):
        contacts_service.save_contact("", "15551234567")
    with pytest.raises(ValueError, match="phone number is required"):
        contacts_service.save_contact("Alex Morgan", "")


@pytest.mark.parametrize(
    "phone",
    ["123", "abcdefgh", "1234567890123456"],
)
def test_contact_creation_rejects_invalid_phone(phone):
    with pytest.raises(ValueError, match="7 to 15 digits"):
        contacts_service.save_contact("Alex Morgan", phone)


def test_contact_creation_rejects_invalid_email():
    with pytest.raises(ValueError, match="valid email"):
        contacts_service.save_contact("Alex Morgan", "15551234567", "not-an-email")


def test_preview_never_creates_contact_until_confirmed():
    service = MagicMock()
    service.people().connections().list.return_value.execute.return_value = {
        "connections": []
    }

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        result = contacts_service.save_contact(
            "Alex Morgan",
            "+1 555 123 4567",
            "alex@example.test",
        )

    assert result["success"] is True
    assert result["created"] is False
    assert result["requires_confirmation"] is True
    assert result["preview"] == {
        "name": "Alex Morgan",
        "phone_numbers": ["+1 555 123 4567"],
        "emails": ["alex@example.test"],
    }
    service.people().createContact.assert_not_called()


def test_duplicate_phone_is_rejected_without_creation():
    service = MagicMock()
    service.people().connections().list.return_value.execute.return_value = {
        "connections": [
            {
                "resourceName": "people/existing",
                "names": [{"displayName": "Existing Contact"}],
                "phoneNumbers": [{"value": "+1 (555) 123-4567"}],
            }
        ]
    }

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        result = contacts_service.save_contact(
            "A New Person",
            "15551234567",
            confirmed=True,
        )

    assert result["success"] is False
    assert result["created"] is False
    assert result["contact"]["name"] == "Existing Contact"
    service.people().createContact.assert_not_called()


def test_confirmed_creation_uses_correct_people_api_fields():
    service = MagicMock()
    service.people().connections().list.return_value.execute.return_value = {
        "connections": []
    }
    service.people().createContact.return_value.execute.return_value = {
        "names": [{"displayName": "Alex Morgan"}],
        "phoneNumbers": [{"value": "15551234567"}],
        "emailAddresses": [{"value": "alex@example.test"}],
    }

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        result = contacts_service.save_contact(
            "Alex Morgan",
            "15551234567",
            "alex@example.test",
            confirmed=True,
        )

    assert result["success"] is True
    assert result["created"] is True
    service.people().createContact.assert_called_once_with(
        body={
            "names": [{"givenName": "Alex Morgan"}],
            "phoneNumbers": [{"value": "15551234567", "type": "mobile"}],
            "emailAddresses": [{"value": "alex@example.test"}],
        },
        personFields=contacts_service.CONTACT_FIELDS,
    )


def test_malformed_created_contact_is_rejected():
    service = MagicMock()
    service.people().connections().list.return_value.execute.return_value = {
        "connections": []
    }
    service.people().createContact.return_value.execute.return_value = []

    with patch.object(contacts_service, "get_contacts_service", return_value=service):
        with pytest.raises(RuntimeError, match="invalid response"):
            contacts_service.save_contact(
                "Alex Morgan", "15551234567", confirmed=True
            )
