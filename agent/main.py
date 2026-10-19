"""
main.py
--------
Terminal interaction and user confirmation flow for the Personal AI Agent.

Responsibilities:
  - Provide an interactive, beginner-friendly terminal chat loop.
  - Maintain a bounded history without separating tool calls from tool results.
  - Highlight actions that require user confirmation (sending emails,
    replies, and trashing messages).
  - Automatically recover from errors without poisoning conversation history.
  - Handle exit, reset, and help commands.
"""

import sys
import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from agent.graph import TOOLS, agent
from agent.tools.confirmation import authorize_tool_call


CONFIRMATION_TOOL_NAMES = {
    "send_email",
    "reply_to_email",
    "archive_messages",
    "trash_messages",
    "create_contact",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "create_task",
    "update_task",
    "complete_task",
    "delete_task",
    "create_reminder",
    "cancel_reminder",
}
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}

# Ensure Windows PowerShell/cmd console handles UTF-8 output cleanly
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def trim_conversation_history(messages: list, max_messages: int = 6) -> list:
    """Trim only complete user turns, keeping tool-call/result pairs together."""
    history = list(messages)
    while len(history) > max_messages:
        user_turns = [
            index
            for index, message in enumerate(history)
            if isinstance(message, HumanMessage)
        ]
        if len(user_turns) < 2:
            break
        del history[: user_turns[1]]
    return history


def print_banner():
    """Display startup banner with instructions."""
    print("=" * 68)
    print("  Personal AI Agent — Gmail, Contacts, Calendar, Tasks & Reminders")
    print("=" * 68)
    print("Capabilities:")
    print("  • Emails:     'Show 5 latest emails', 'Summarize unread', 'Draft to...', 'Send'")
    print("  • Contacts:   'Find Alex in contacts', 'Add contact Alex with phone 15551234567'")
    print("  • Calendar:   'What's on my calendar today?', 'Schedule meeting tomorrow at 10 AM'")
    print("  • Tasks:      'Show pending tasks', 'Add task Study Python by Friday', 'Mark complete'")
    print("  • Reminders:  'Remind me to study tomorrow at 7 PM', 'Show scheduled reminders'")
    print("\nCommands:")
    print("  • Type 'clear' or 'reset' to start a fresh conversation")
    print("  • Type 'help' to see sample commands")
    print("  • Type 'exit' or 'quit' to close the assistant")
    print("=" * 68)
    print()


def print_help():
    """Print example natural language commands."""
    print("\n--- Example Commands ---")
    print("1. 'What is on my calendar today?'")
    print("2. 'Schedule a meeting tomorrow at 10 AM for 30 minutes'")
    print("3. 'Show my pending tasks'")
    print("4. 'Add a task to complete my assignment by Friday'")
    print("5. 'Remind me to study Python tomorrow at 7 PM'")
    print("6. 'Show my scheduled reminders'")
    print("7. 'Show me my 5 latest emails'")
    print("8. 'Find Alex in my contacts'")
    print("------------------------\n")


def _requires_confirmation(content) -> bool:
    if isinstance(content, dict):
        return content.get("requires_confirmation") is True
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        if isinstance(decoded, dict) and decoded.get("requires_confirmation") is True:
            return True
        return is_confirmation_request(content)
    return False


def is_confirmation_request(text: str) -> bool:
    """Recognize explicit confirmation language in a tool preview."""
    lowered = text.casefold()
    return any(
        phrase in lowered
        for phrase in (
            "confirmation required",
            "please confirm:",
            "confirm before it is created",
        )
    )


def _pending_confirmations(messages: list) -> list[dict]:
    calls = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call.get("name") in CONFIRMATION_TOOL_NAMES:
                    calls[call.get("id")] = call

    pending = []
    for message in messages:
        if (
            isinstance(message, ToolMessage)
            and message.tool_call_id in calls
            and message.name == calls[message.tool_call_id]["name"]
            and _requires_confirmation(message.content)
        ):
            call = calls[message.tool_call_id]
            pending.append(
                {
                    "tool_name": call["name"],
                    "arguments": dict(call.get("args") or {}),
                    "preview": message.content,
                }
            )
    return pending


def _format_tool_result(result) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


def _is_confirmation(text: str) -> bool:
    return text.strip().casefold() in {"yes", "confirm"}


def _is_cancellation(text: str) -> bool:
    return text.strip().casefold() in {"no", "cancel"}


def _messages_for_turn(messages: list, user_message: HumanMessage) -> list:
    for index, message in enumerate(messages):
        if message is user_message:
            return messages[index:]
    return messages


def run_session():
    """Run the main interactive chat session."""
    print_banner()

    # Maintain conversation messages across multiple turns
    conversation_history = []
    pending_action = None

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        command = user_input.lower()
        if command in {"exit", "quit", "q"}:
            print("\nGoodbye!")
            break

        if command in {"clear", "reset"}:
            conversation_history = []
            pending_action = None
            print("\n[Conversation history reset. Starting fresh!]\n")
            continue

        if command == "help":
            print_help()
            continue

        if pending_action and _is_confirmation(user_input):
            tool_name = pending_action["tool_name"]
            tool_args = dict(pending_action["arguments"])
            tool_args["confirmed"] = True
            try:
                with authorize_tool_call(tool_name):
                    result = TOOLS_BY_NAME[tool_name].invoke(tool_args)
                result_text = _format_tool_result(result)
                conversation_history.extend(
                    [
                        HumanMessage(content="yes"),
                        AIMessage(content=f"Confirmed action result:\n{result_text}"),
                    ]
                )
                print(f"\nAgent: {result_text}\n")
            except Exception as error:
                conversation_history.append(HumanMessage(content="yes"))
                conversation_history.append(
                    AIMessage(
                        content=(
                            "The confirmed action failed "
                            f"({type(error).__name__}). No successful result was received."
                        )
                    )
                )
                print(
                    "\nError: The confirmed action failed "
                    f"({type(error).__name__}). No success was reported.\n"
                )
            pending_action = None
            conversation_history = trim_conversation_history(conversation_history)
            continue

        if pending_action and _is_cancellation(user_input):
            conversation_history.extend(
                [
                    HumanMessage(content="no"),
                    AIMessage(content="The pending action was cancelled. No change was made."),
                ]
            )
            pending_action = None
            print("\nAgent: The pending action was cancelled. No change was made.\n")
            continue

        if _is_confirmation(user_input) or _is_cancellation(user_input):
            print("\nAgent: There is no pending action to confirm or cancel.\n")
            continue

        if pending_action:
            pending_action = None
            print("[The previous action was not confirmed and will not be executed.]")

        # Add user message to history
        user_message = HumanMessage(content=user_input)
        conversation_history.append(user_message)
        # Keep complete user turns so no tool result is separated from its call.
        conversation_history = trim_conversation_history(conversation_history)

        try:
            # Invoke the LangGraph agent
            result = agent.invoke({"messages": conversation_history})

            # Update conversation history with the full message list
            conversation_history = result["messages"]

            confirmations = _pending_confirmations(
                _messages_for_turn(conversation_history, user_message)
            )
            if len(confirmations) == 1:
                pending_action = confirmations[0]
                preview = _format_tool_result(pending_action["preview"])
                print(
                    "\nAgent action preview:\n"
                    f"{preview}\n\n"
                    "No change has been made. Type 'yes' to execute this exact action, "
                    "or 'no' to cancel.\n"
                )
                continue
            if len(confirmations) > 1:
                print(
                    "\nAgent: Multiple actions require confirmation. No changes were made; "
                    "request one action at a time.\n"
                )
                continue

            # The final assistant response is the last message
            assistant_reply = str(conversation_history[-1].content)

            print(f"\nAgent: {assistant_reply}\n")

        except Exception as error:
            # Remove the last user message so a failed call does not poison subsequent turns
            if conversation_history and conversation_history[-1] is user_message:
                conversation_history.pop()

            print(
                "\nError: The request failed "
                f"({type(error).__name__}). No successful operation was reported.\n"
            )


if __name__ == "__main__":
    run_session()