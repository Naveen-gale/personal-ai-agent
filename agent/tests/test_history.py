"""Conversation history trimming must preserve complete tool-call sequences."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.main import is_confirmation_request, trim_conversation_history


def test_contact_preview_is_recognized_as_confirmation_request():
    assert is_confirmation_request(
        "Review this contact and confirm before it is created."
    )


def test_trimming_drops_whole_older_turns_without_orphaning_tool_results():
    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "find_contact",
                "args": {"query": "Alex"},
                "id": "find-1",
                "type": "tool_call",
            }
        ],
    )
    history = [
        HumanMessage(content="old turn"),
        AIMessage(content="old answer"),
        HumanMessage(content="find Alex"),
        tool_call,
        ToolMessage(content="contact result", tool_call_id="find-1", name="find_contact"),
        AIMessage(content="Found Alex."),
        HumanMessage(content="new turn"),
    ]

    result = trim_conversation_history(history, max_messages=6)

    assert result[0].content == "find Alex"
    assert result[1].tool_calls[0]["id"] == "find-1"
    assert result[2].tool_call_id == "find-1"
    assert not any(
        isinstance(message, ToolMessage) and message.tool_call_id != "find-1"
        for message in result
    )


def test_large_current_turn_is_not_cut_in_the_middle():
    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "find_contact",
                "args": {"query": "Alex"},
                "id": "find-2",
                "type": "tool_call",
            }
        ],
    )
    history = [
        HumanMessage(content="find Alex"),
        tool_call,
        ToolMessage(content="result", tool_call_id="find-2", name="find_contact"),
        AIMessage(content="Found Alex."),
        AIMessage(content="Additional assistant response."),
        AIMessage(content="Final response."),
    ]

    result = trim_conversation_history(history, max_messages=3)

    assert result == history
