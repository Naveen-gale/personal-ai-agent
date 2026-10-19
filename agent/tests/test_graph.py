"""
tests/test_graph.py
--------------------
Verifies that the LangGraph workflow compiles and that all 13 tools are registered.

These tests use mocks and do NOT invoke real APIs or consume Groq quota.

Run with:
    .\\agent\\.venv\\Scripts\\python.exe -m pytest agent\\tests\\test_graph.py -v
"""

from unittest.mock import patch, MagicMock


EXPECTED_TOOL_NAMES = [
    # Gmail Tools
    "search_gmail",
    "read_email",
    "get_unread_emails",
    "create_draft",
    "send_email",
    "reply_to_email",
    "mark_as_read",
    "mark_as_unread",
    "archive_messages",
    "trash_messages",
    "create_label",
    "apply_label",
    # General Tools
    "get_current_datetime",
    # Contacts Tools
    "find_contact",
    "create_contact",
    # Calendar Tools
    "get_today_events",
    "list_calendar_events",
    "search_calendar_events",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    # Tasks Tools
    "list_pending_tasks",
    "list_completed_tasks",
    "create_task",
    "update_task",
    "complete_task",
    "delete_task",
    # Reminder Tools
    "create_reminder",
    "list_reminders",
    "cancel_reminder",
]


def test_agent_compiles():
    """The compiled agent must be importable and not None."""
    from agent.graph import agent
    assert agent is not None, "agent must be compiled successfully"


def test_all_30_tools_are_registered():
    """All supported capability tools must be present in graph.py."""
    from agent.graph import TOOLS

    registered_names = [t.name for t in TOOLS]
    assert len(registered_names) == 30, f"Expected 30 tools, found {len(registered_names)}"

    for expected in EXPECTED_TOOL_NAMES:
        assert expected in registered_names, f"Tool '{expected}' is missing from graph TOOLS"
    assert len(set(registered_names)) == len(registered_names)


def test_agent_invoke_with_mock_llm():
    """
    Verify the agent graph can be invoked through StateGraph with a mocked LLM.
    Ensures message state propagation works as expected.
    """
    from langchain_core.messages import HumanMessage, AIMessage

    mock_response = AIMessage(content="Hello! How can I help you today?")

    with patch("agent.nodes.assistant_node._base_llm") as mock_llm:
        mock_bound = MagicMock()
        mock_bound.invoke.return_value = mock_response
        mock_llm.bind_tools.return_value = mock_bound

        import importlib
        import agent.graph as graph_mod
        importlib.reload(graph_mod)

        result = graph_mod.agent.invoke(
            {"messages": [HumanMessage(content="Hello")]}
        )

    assert "messages" in result
    assert len(result["messages"]) > 0
    assert result["messages"][-1].content == "Hello! How can I help you today?"


def test_contact_tool_call_receives_matching_result_and_assistant_reply():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "find_contact",
                "args": {"query": "Alex"},
                "id": "contact-call-1",
                "type": "tool_call",
            }
        ],
    )
    final_response = AIMessage(content="I found Alex.")

    with patch("agent.nodes.assistant_node._base_llm") as mock_llm, patch(
        "agent.tools.contacts_tools.search_contacts_service",
        return_value={
            "success": True,
            "matches": [{"name": "Alex Morgan", "phone_numbers": [], "emails": []}],
            "count": 1,
            "message": "Search complete.",
        },
    ):
        mock_bound = MagicMock()
        mock_bound.invoke.side_effect = [tool_call, final_response]
        mock_llm.bind_tools.return_value = mock_bound

        import importlib
        import agent.graph as graph_mod
        importlib.reload(graph_mod)
        result = graph_mod.agent.invoke(
            {"messages": [HumanMessage(content="Find Alex")]}
        )

    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "contact-call-1"
    assert tool_messages[0].name == "find_contact"
    assert result["messages"][-1].content == "I found Alex."


def test_calendar_tool_call_routing():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_today_events",
                "args": {},
                "id": "cal-call-1",
                "type": "tool_call",
            }
        ],
    )
    final_response = AIMessage(content="You have no meetings today.")

    with patch("agent.nodes.assistant_node._base_llm") as mock_llm, patch(
        "agent.tools.calendar_tools.get_today_events_service",
        return_value={"success": True, "events": [], "count": 0, "time_zone": "Asia/Kolkata"},
    ):
        mock_bound = MagicMock()
        mock_bound.invoke.side_effect = [tool_call, final_response]
        mock_llm.bind_tools.return_value = mock_bound

        import importlib
        import agent.graph as graph_mod
        importlib.reload(graph_mod)
        result = graph_mod.agent.invoke(
            {"messages": [HumanMessage(content="What is on my calendar today?")]}
        )

    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "cal-call-1"
    assert tool_messages[0].name == "get_today_events"
    assert result["messages"][-1].content == "You have no meetings today."


def test_model_cannot_bypass_email_confirmation_argument():
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "send_email",
                "args": {
                    "to": "owner@example.test",
                    "subject": "Test",
                    "body": "Preview only",
                    "confirmed": True,
                },
                "id": "send-call-1",
                "type": "tool_call",
            }
        ],
    )
    final_response = AIMessage(content="The email has not been sent.")

    with patch("agent.nodes.assistant_node._base_llm") as mock_llm, patch(
        "agent.services.gmail_service.send_email"
    ) as send_email:
        mock_bound = MagicMock()
        mock_bound.invoke.side_effect = [tool_call, final_response]
        mock_llm.bind_tools.return_value = mock_bound

        import importlib
        import agent.graph as graph_mod
        importlib.reload(graph_mod)
        result = graph_mod.agent.invoke(
            {"messages": [HumanMessage(content="Send the email")]}
        )

    send_email.assert_not_called()
    tool_messages = [
        message for message in result["messages"] if isinstance(message, ToolMessage)
    ]
    assert len(tool_messages) == 1
    assert "CONFIRMATION REQUIRED" in tool_messages[0].content
