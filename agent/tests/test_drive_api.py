"""Mocked tests for Drive API authorization gates and web confirmations."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from agent import api
from agent.tools.confirmation import consume_tool_authorization


client = TestClient(
    api.app,
    headers={"Authorization": "Bearer test-agent-service-token"},
)


@pytest.fixture(autouse=True)
def configure_service_token(monkeypatch):
    monkeypatch.setenv("AGENT_SERVICE_TOKEN", "test-agent-service-token")


def test_rename_endpoint_requires_explicit_confirmation():
    with patch.object(api.drive_service, "rename_drive_item") as rename:
        response = client.patch(
            "/api/drive/files/file-1",
            json={"name": "Final Report.pdf", "confirmed": False},
        )
    assert response.status_code == 400
    rename.assert_not_called()


def test_delete_endpoint_requires_explicit_confirmation():
    with patch.object(api.drive_service, "delete_drive_item") as delete:
        response = client.request(
            "DELETE",
            "/api/drive/files/file-1",
            json={"confirmed": False},
        )
    assert response.status_code == 400
    delete.assert_not_called()


def test_chat_confirmation_authorizes_only_the_stored_tool_call():
    api._PENDING_CHAT_CONFIRMATIONS.clear()
    tool_call = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "delete_drive_item",
                "args": {"file_id": "file-1", "confirmed": False},
                "id": "delete-call",
                "type": "tool_call",
            }
        ],
    )
    tool_result = ToolMessage(
        content=json.dumps(
            {"success": False, "requires_confirmation": True, "message": "Confirm trash"}
        ),
        tool_call_id="delete-call",
        name="delete_drive_item",
    )
    confirmations = api._save_pending_confirmations([tool_call, tool_result])
    assert len(confirmations) == 1
    confirmation_id = confirmations[0]["confirmation_id"]

    tool = MagicMock()
    tool.invoke.side_effect = lambda arguments: {
        "authorized": consume_tool_authorization("delete_drive_item"),
        "file_id": arguments["file_id"],
    }
    with patch.dict(api._TOOLS_BY_NAME, {"delete_drive_item": tool}):
        response = client.post(
            "/api/chat/confirm",
            json={"confirmation_id": confirmation_id, "decision": "yes"},
        )

    assert response.status_code == 200
    assert json.loads(response.json()["reply"]) == {
        "authorized": True,
        "file_id": "file-1",
    }
    tool.invoke.assert_called_once_with({"file_id": "file-1", "confirmed": True})


def test_cancelled_confirmation_does_not_invoke_tool():
    confirmation_id = "cancel-me"
    api._PENDING_CHAT_CONFIRMATIONS[confirmation_id] = {
        "tool_name": "delete_drive_item",
        "arguments": {"file_id": "file-2"},
        "expires_at": time.monotonic() + 60,
    }
    tool = MagicMock()
    with patch.dict(api._TOOLS_BY_NAME, {"delete_drive_item": tool}):
        response = client.post(
            "/api/chat/confirm",
            json={"confirmation_id": confirmation_id, "decision": "no"},
        )
    assert response.status_code == 200
    assert "cancelled" in response.json()["reply"]
    tool.invoke.assert_not_called()


def test_chat_includes_imported_attachment_text_as_current_turn_data():
    result = {"messages": [AIMessage(content="I read the document.")]}
    with patch.object(api.agent, "invoke", return_value=result) as invoke:
        response = client.post(
            "/api/chat",
            json={
                "message": "Summarize this.",
                "history": [],
                "attachments": [{"name": "notes.txt", "text": "The project is due Friday."}],
            },
        )
    assert response.status_code == 200
    sent = invoke.call_args.args[0]["messages"][-1].content
    assert "[Untrusted attachment: notes.txt]" in sent
    assert "The project is due Friday." in sent
