"""CLI confirmation tests use synthetic tool results and mocked provider calls."""

from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from agent import main


def test_cli_executes_exact_pending_action_only_after_yes(capsys):
    call = {
        "name": "send_email",
        "args": {
            "to": "owner@example.test",
            "subject": "Test",
            "body": "Approved text",
            "confirmed": True,
        },
        "id": "call-1",
        "type": "tool_call",
    }

    def invoke(state):
        return {
            "messages": [
                *state["messages"],
                AIMessage(content="", tool_calls=[call]),
                ToolMessage(
                    content=(
                        "CONFIRMATION REQUIRED BEFORE SENDING:\n"
                        "Recipient: owner@example.test\n"
                        "Subject: Test\nBody: Approved text"
                    ),
                    tool_call_id="call-1",
                    name="send_email",
                ),
                AIMessage(content="This email has not been sent."),
            ]
        }

    with (
        patch.object(main.agent, "invoke", side_effect=invoke) as agent_invoke,
        patch(
            "agent.services.gmail_service.send_email",
            return_value={
                "id": "sent-1",
                "to": "owner@example.test",
                "subject": "Test",
            },
        ) as send_email,
        patch("builtins.input", side_effect=["Send it", "yes", "exit"]),
    ):
        main.run_session()

    agent_invoke.assert_called_once()
    send_email.assert_called_once_with(
        to="owner@example.test",
        subject="Test",
        body="Approved text",
    )
    output = capsys.readouterr().out
    assert "No change has been made" in output
    assert "Email sent successfully" in output
