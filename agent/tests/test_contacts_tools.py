"""Tests for Contacts LangChain tools and agent registration."""

from unittest.mock import patch

from agent.tools.contacts_tools import CONTACT_TOOLS, create_contact, find_contact
from agent.tools.confirmation import authorize_tool_call


def test_contacts_tools_have_names_schemas_and_invocation():
    assert [tool.name for tool in CONTACT_TOOLS] == ["find_contact", "create_contact"]
    assert all(tool.name and tool.args_schema is not None for tool in CONTACT_TOOLS)

    with patch(
        "agent.tools.contacts_tools.search_contacts_service",
        return_value={
            "success": True,
            "matches": [{"name": "Alex Morgan", "phone_numbers": ["15551234567"], "emails": []}],
            "count": 1,
            "message": "Search complete.",
        },
    ) as search:
        result = find_contact.invoke({"query": "Alex"})

    assert result["matches"][0]["phone_numbers"] == ["15551234567"]
    search.assert_called_once_with("Alex", 10)

    with patch(
        "agent.tools.contacts_tools.save_contact_service",
        return_value={
            "success": True,
            "created": False,
            "requires_confirmation": True,
            "preview": {"name": "Alex", "phone_numbers": ["15551234567"], "emails": []},
            "message": "Review this contact and confirm before it is created.",
        },
    ) as save:
        result = create_contact.invoke(
            {"name": "Alex", "phone": "15551234567", "confirmed": False}
        )

    assert result["requires_confirmation"] is True
    save.assert_called_once_with("Alex", "15551234567", "", False)


def test_model_confirmation_argument_cannot_create_contact():
    with patch(
        "agent.tools.contacts_tools.save_contact_service",
        return_value={"success": True, "created": False, "requires_confirmation": True},
    ) as save:
        result = create_contact.invoke(
            {"name": "Alex", "phone": "15551234567", "confirmed": True}
        )

    assert result["requires_confirmation"] is True
    save.assert_called_once_with("Alex", "15551234567", "", False)


def test_cli_authorization_is_one_shot_for_contact_creation():
    with patch(
        "agent.tools.contacts_tools.save_contact_service",
        side_effect=[
            {"success": True, "created": True},
            {"success": True, "created": False, "requires_confirmation": True},
        ],
    ) as save:
        with authorize_tool_call("create_contact"):
            result = create_contact.invoke(
                {"name": "Alex", "phone": "15551234567", "confirmed": True}
            )
        repeated = create_contact.invoke(
            {"name": "Alex", "phone": "15551234567", "confirmed": True}
        )

    assert result["created"] is True
    assert repeated["created"] is False
    assert [call.args[3] for call in save.call_args_list] == [True, False]


def test_contacts_tools_return_errors_instead_of_raising():
    with patch(
        "agent.tools.contacts_tools.search_contacts_service",
        side_effect=RuntimeError("Contacts permissions are missing."),
    ):
        result = find_contact.invoke({"query": "Alex"})
    assert result["success"] is False
    assert "permissions are missing" in result["message"]

    with patch(
        "agent.tools.contacts_tools.save_contact_service",
        side_effect=ValueError("Contact phone number is required."),
    ):
        result = create_contact.invoke({"name": "Alex", "phone": ""})
    assert result["success"] is False
    assert result["created"] is False
    assert "phone number is required" in result["message"]
