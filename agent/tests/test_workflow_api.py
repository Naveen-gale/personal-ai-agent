"""
tests/test_workflow_api.py
--------------------------
Integration tests for the FastAPI REST API endpoints using TestClient.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from agent.api import app
from agent.services import workflow_service


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AGENT_SERVICE_TOKEN", "test-agent-service-token")
    db_file = tmp_path / "test_api_workflows.db"
    workflow_service.init_workflow_db(db_file)
    with patch("agent.api.DEFAULT_WORKFLOW_DB_PATH", db_file), patch(
        "agent.services.workflow_service.DEFAULT_WORKFLOW_DB_PATH", db_file
    ):
        yield TestClient(app, headers={"Authorization": "Bearer test-agent-service-token"})


def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_agent_api_requires_backend_service_token(monkeypatch):
    monkeypatch.setenv("AGENT_SERVICE_TOKEN", "test-agent-service-token")
    response = TestClient(app).get("/api/health")
    assert response.status_code == 401


def test_api_get_tools(client):
    res = client.get("/api/tools")
    assert res.status_code == 200
    tools = res.json()["tools"]
    tool_names = [t["name"] for t in tools]
    assert "get_unread_emails" in tool_names
    assert "get_today_events" in tool_names
    assert "llm_synthesize" in tool_names


def test_api_workflow_crud(client):
    # 1. Create workflow
    payload = {
        "name": "API Test Workflow",
        "description": "Testing API creation",
        "trigger_type": "scheduled",
        "trigger_config": {"recurrence": "daily", "time": "09:00"},
        "steps": [{"id": "s1", "name": "Get unread", "tool": "get_unread_emails", "inputs": {}}],
        "status": "active",
    }
    create_res = client.post("/api/workflows", json=payload)
    assert create_res.status_code == 201
    created_wf = create_res.json()["workflow"]
    wf_id = created_wf["id"]
    assert created_wf["name"] == "API Test Workflow"

    # 2. Get single
    get_res = client.get(f"/api/workflows/{wf_id}")
    assert get_res.status_code == 200
    assert get_res.json()["workflow"]["id"] == wf_id

    # 3. Update
    put_res = client.put(f"/api/workflows/{wf_id}", json={"name": "Updated API Name"})
    assert put_res.status_code == 200
    assert put_res.json()["workflow"]["name"] == "Updated API Name"

    # 4. Pause and Resume
    pause_res = client.post(f"/api/workflows/{wf_id}/pause")
    assert pause_res.status_code == 200
    assert pause_res.json()["workflow"]["status"] == "paused"

    resume_res = client.post(f"/api/workflows/{wf_id}/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["workflow"]["status"] == "active"

    # 5. Delete
    del_res = client.delete(f"/api/workflows/{wf_id}")
    assert del_res.status_code == 200

    # 6. Verify 404 after deletion
    get_after = client.get(f"/api/workflows/{wf_id}")
    assert get_after.status_code == 404


def test_api_manual_run(client):
    payload = {
        "name": "Run Me",
        "steps": [{"id": "s1", "tool": "get_today_events", "inputs": {}}],
    }
    create_res = client.post("/api/workflows", json=payload)
    wf_id = create_res.json()["workflow"]["id"]

    with patch(
        "agent.services.workflow_engine.execute_tool",
        return_value={"events": [], "count": 0},
    ):
        run_res = client.post(f"/api/workflows/{wf_id}/run")

    assert run_res.status_code == 200
    assert run_res.json()["execution"]["status"] == "completed"


def test_api_chat_endpoint(client):
    with patch("agent.api.agent.invoke") as mock_invoke:
        mock_msg = MagicMock()
        mock_msg.content = "Here are your today events."
        mock_invoke.return_value = {"messages": [mock_msg]}

        chat_res = client.post(
            "/api/chat", json={"message": "What is on my calendar?", "history": []}
        )

    assert chat_res.status_code == 200
    assert "Here are your today events" in chat_res.json()["reply"]
