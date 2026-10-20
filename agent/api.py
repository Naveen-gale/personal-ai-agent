"""
api.py
------
FastAPI REST API server for the Personal AI Agent and Workflow Automation System.

Endpoints:
  - Workflows: CRUD, manual execution, pause, resume
  - Executions: List history, step results, retry
  - Approvals: View pending, approve, reject
  - Tools: Introspect whitelisted workflow tools
  - Chat: Web-based interactive chat invoking LangGraph agent
"""

import os
import secrets
import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, Field
from googleapiclient.errors import HttpError
import requests

from agent.graph import TOOLS, agent
from agent.services import drive_service, photos_picker_service
from agent.tools.confirmation import authorize_tool_call
from agent.services.workflow_adapters import get_available_tools
from agent.services.workflow_engine import (
    approve_and_resume_execution,
    execute_workflow,
    validate_workflow,
)
from agent.services.workflow_scheduler import calculate_next_workflow_run
from agent.services.workflow_service import (
    DEFAULT_WORKFLOW_DB_PATH,
    create_execution,
    delete_workflow,
    get_execution,
    get_pending_approvals,
    get_workflow,
    init_workflow_db,
    list_executions,
    list_workflows,
    save_workflow,
    uses_mongodb,
    update_workflow_status,
)
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure database schema is initialized on server startup."""
    if uses_mongodb():
        init_workflow_db()
    else:
        init_workflow_db(DEFAULT_WORKFLOW_DB_PATH)
    yield


app = FastAPI(
    title="Personal AI Agent — Workflow Automation API",
    description="Production-grade REST API for LangGraph agent and automated workflows.",
    version="1.0.0",
    lifespan=lifespan,
)

@app.middleware("http")
async def require_backend_service_auth(request: Request, call_next):
    expected_token = os.getenv("AGENT_SERVICE_TOKEN", "").strip()
    supplied_token = request.headers.get("authorization", "")
    if not expected_token:
        return Response(
            content='{"detail":"Agent service authentication is not configured."}',
            status_code=503,
            media_type="application/json",
        )
    if not secrets.compare_digest(supplied_token, f"Bearer {expected_token}"):
        return Response(
            content='{"detail":"Authentication required."}',
            status_code=401,
            media_type="application/json",
        )
    return await call_next(request)


# ── Pydantic Request Models ───────────────────────────────────────────────────

class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., description="Descriptive workflow name")
    description: str = Field("", description="Optional workflow description")
    trigger_type: str = Field("manual", description="manual, scheduled, or event")
    trigger_config: dict[str, Any] = Field(default_factory=dict, description="Schedule/event configuration")
    steps: list[dict[str, Any]] = Field(..., description="Ordered list of workflow steps")
    status: str = Field("active", description="active, paused, or draft")


class WorkflowUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    trigger_type: str | None = None
    trigger_config: dict[str, Any] | None = None
    steps: list[dict[str, Any]] | None = None
    status: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: str = Field(..., description="'approved' or 'rejected'")


class ChatRequest(BaseModel):
    message: str = Field(..., description="User chat message")
    history: list[dict[str, str]] = Field(default_factory=list, description="Recent conversation turns")
    attachments: list[dict[str, str]] = Field(default_factory=list)


class FolderCreateRequest(BaseModel):
    name: str
    parent_id: str | None = None


class DriveRenameRequest(BaseModel):
    name: str
    confirmed: bool = False


class DriveMoveRequest(BaseModel):
    destination_folder_id: str
    confirmed: bool = False


class DriveCopyRequest(BaseModel):
    name: str | None = None
    parent_id: str | None = None


class DriveDeleteRequest(BaseModel):
    confirmed: bool = False


class PhotosSaveRequest(BaseModel):
    media_item_ids: list[str]
    parent_id: str | None = None


class ChatConfirmationRequest(BaseModel):
    confirmation_id: str
    decision: str


class InternalAgentRunRequest(BaseModel):
    user_id: str
    message: str = Field(..., min_length=1, max_length=20_000)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=14)
    attachments: list[dict[str, str]] = Field(default_factory=list, max_length=10)


class InternalAgentConfirmationRequest(BaseModel):
    user_id: str
    tool_name: str
    arguments: dict[str, Any]


MAX_UPLOAD_BYTES = int(os.getenv("DRIVE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_CHAT_ATTACHMENT_TEXT = 500_000
_PENDING_CHAT_CONFIRMATIONS: dict[str, dict[str, Any]] = {}
_CONFIRMATION_TOOL_NAMES = {
    "rename_drive_item",
    "move_drive_item",
    "delete_drive_item",
}
_TOOLS_BY_NAME = {registered_tool.name: registered_tool for registered_tool in TOOLS}


# ── System & Tools Endpoints ──────────────────────────────────────────────────

@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "personal-ai-agent", "version": "1.0.0"}


@app.get("/api/tools")
def get_tools():
    """Return all whitelisted workflow tools and their parameter schemas."""
    return {"success": True, "tools": get_available_tools()}


def _drive_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, PermissionError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    if isinstance(error, RuntimeError):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(error, (HttpError, requests.HTTPError)):
        response = error.resp if isinstance(error, HttpError) else error.response
        code = getattr(response, "status", None) or getattr(response, "status_code", 502)
        if code == 401:
            detail = "Google authorization expired. Reauthorize with: python -m agent.auth.gmail_auth"
        elif code == 403:
            detail = (
                "Google denied this operation. Check the file permissions, enabled APIs, "
                "and granted OAuth scopes."
            )
        elif code == 404:
            detail = "The requested Google Drive or Photos item was not found."
        elif code == 429:
            detail = "Google API quota exceeded. Wait before retrying."
        else:
            detail = f"Google API request failed with status {code}."
        return HTTPException(status_code=code if 400 <= code < 600 else 502, detail=detail)
    if isinstance(error, requests.RequestException):
        return HTTPException(status_code=502, detail="Google Photos request failed. Retry the operation.")
    return HTTPException(status_code=502, detail=f"Google integration failed: {type(error).__name__}.")


@app.get("/api/drive/files")
def browse_drive_files(
    folder_id: str | None = None,
    q: str | None = None,
    mime_type: str | None = None,
    page_token: str | None = None,
    page_size: int = Query(50, ge=1, le=100),
):
    try:
        result = drive_service.list_drive_files(
            parent_id=folder_id,
            name_query=q,
            mime_type=mime_type,
            page_token=page_token,
            page_size=page_size,
            all_files=bool(q and not folder_id),
        )
        return {"success": True, **result}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.get("/api/drive/files/{file_id}/content")
def import_drive_file(file_id: str):
    try:
        return {"success": True, **drive_service.get_drive_file_content(file_id)}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.get("/api/drive/files/{file_id}/download")
def download_drive_item(file_id: str):
    try:
        from urllib.parse import quote

        result = drive_service.download_drive_file(file_id)
        filename = quote(result["filename"])
        return Response(
            content=result["content"],
            media_type=result["mime_type"],
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.post("/api/drive/folders", status_code=status.HTTP_201_CREATED)
def create_drive_folder(req: FolderCreateRequest):
    try:
        return {
            "success": True,
            "folder": drive_service.create_folder(req.name, req.parent_id),
        }
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.get("/api/drive/folders/resolve")
def resolve_drive_folder(path: str, create_missing: bool = False):
    try:
        folder = drive_service.resolve_folder_path(path, create_missing=create_missing)
        return {"success": True, "folder": folder}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.patch("/api/drive/files/{file_id}")
def rename_drive_file(file_id: str, req: DriveRenameRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before renaming a Drive item.")
    try:
        item = drive_service.rename_drive_item(file_id, req.name)
        return {"success": True, "item": item}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.post("/api/drive/files/{file_id}/move")
def move_drive_file(file_id: str, req: DriveMoveRequest):
    if not req.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before moving a Drive item.")
    try:
        item = drive_service.move_drive_item(file_id, req.destination_folder_id)
        return {"success": True, "item": item}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.post("/api/drive/files/{file_id}/copy")
def copy_drive_file(file_id: str, req: DriveCopyRequest):
    try:
        item = drive_service.copy_drive_file(file_id, req.name, req.parent_id)
        return {"success": True, "item": item}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.delete("/api/drive/files/{file_id}")
def trash_drive_file(file_id: str, req: DriveDeleteRequest):
    if not req.confirmed:
        raise HTTPException(
            status_code=400,
            detail="Explicit confirmation is required before moving a Drive item to trash.",
        )
    try:
        item = drive_service.delete_drive_item(file_id)
        return {"success": True, "item": item}
    except (HttpError, FileNotFoundError, PermissionError, ValueError, RuntimeError) as exc:
        raise _drive_http_exception(exc) from exc


@app.post("/api/drive/upload", status_code=status.HTTP_201_CREATED)
async def upload_drive_file(
    file: UploadFile = File(...),
    parent_id: str | None = Form(None),
    operation_id: str = Form(...),
):
    temp_path = None
    try:
        filename = drive_service.validate_filename(file.filename or "")
        mime_type = file.content_type or "application/octet-stream"
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(filename).suffix) as temp_file:
            temp_path = Path(temp_file.name)
            size = 0
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise ValueError(
                        f"File exceeds the {MAX_UPLOAD_BYTES}-byte upload limit."
                    )
                temp_file.write(chunk)
        uploaded = await asyncio.to_thread(
            drive_service.upload_file,
            temp_path,
            filename,
            mime_type,
            parent_id,
            operation_id,
        )
        return {"success": True, "file": uploaded}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)
        await file.close()


@app.post("/api/photos/sessions", status_code=status.HTTP_201_CREATED)
def create_photos_picker_session():
    try:
        return {"success": True, "session": photos_picker_service.create_picker_session()}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.get("/api/photos/sessions/{session_id}")
def get_photos_picker_session(session_id: str):
    try:
        return {"success": True, "session": photos_picker_service.get_picker_session(session_id)}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.get("/api/photos/sessions/{session_id}/items")
def get_photos_picker_items(
    session_id: str,
    page_token: str | None = None,
    page_size: int = Query(50, ge=1, le=100),
):
    try:
        return {
            "success": True,
            **photos_picker_service.list_selected_media(
                session_id, page_token=page_token, page_size=page_size
            ),
        }
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.post("/api/photos/sessions/{session_id}/save-to-drive")
def save_photos_to_drive(session_id: str, req: PhotosSaveRequest):
    try:
        files = photos_picker_service.save_selected_media_to_drive(
            session_id, req.media_item_ids, req.parent_id
        )
        return {"success": True, "files": files}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


@app.delete("/api/photos/sessions/{session_id}")
def delete_photos_picker_session(session_id: str):
    try:
        photos_picker_service.delete_picker_session(session_id)
        return {"success": True}
    except (
        HttpError,
        FileNotFoundError,
        PermissionError,
        ValueError,
        RuntimeError,
        requests.RequestException,
    ) as exc:
        raise _drive_http_exception(exc) from exc


# ── Workflows Endpoints ───────────────────────────────────────────────────────

@app.get("/api/workflows")
def get_workflows(status: str | None = Query(None, description="Filter by active, paused, draft, or all")):
    return {"success": True, "workflows": list_workflows(status=status)}


@app.post("/api/workflows", status_code=status.HTTP_201_CREATED)
def create_workflow(req: WorkflowCreateRequest):
    data = req.model_dump()
    is_valid, msg = validate_workflow(data)
    if not is_valid:
        raise HTTPException(status_code=400, detail=msg)

    if data.get("trigger_type") == "scheduled":
        data["next_run_utc"] = calculate_next_workflow_run(data.get("trigger_config") or {})

    saved = save_workflow(data)
    return {"success": True, "workflow": saved}


@app.get("/api/workflows/{workflow_id}")
def get_single_workflow(workflow_id: str):
    wf = get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"success": True, "workflow": wf}


@app.put("/api/workflows/{workflow_id}")
def update_existing_workflow(workflow_id: str, req: WorkflowUpdateRequest):
    existing = get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Workflow not found")

    merged = dict(existing)
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    merged.update(updates)

    is_valid, msg = validate_workflow(merged)
    if not is_valid:
        raise HTTPException(status_code=400, detail=msg)

    if merged.get("trigger_type") == "scheduled":
        merged["next_run_utc"] = calculate_next_workflow_run(merged.get("trigger_config") or {})

    saved = save_workflow(merged)
    return {"success": True, "workflow": saved}


@app.delete("/api/workflows/{workflow_id}")
def delete_single_workflow(workflow_id: str):
    deleted = delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"success": True, "message": "Workflow deleted successfully"}


@app.post("/api/workflows/{workflow_id}/run")
def trigger_workflow_run(workflow_id: str):
    wf = get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        execution = execute_workflow(wf["id"], trigger_type="manual")
        return {"success": True, "execution": execution}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/workflows/{workflow_id}/pause")
def pause_single_workflow(workflow_id: str):
    try:
        updated = update_workflow_status(workflow_id, new_status="paused")
        return {"success": True, "workflow": updated}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/workflows/{workflow_id}/resume")
def resume_single_workflow(workflow_id: str):
    try:
        updated = update_workflow_status(workflow_id, new_status="active")
        return {"success": True, "workflow": updated}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/workflows/{workflow_id}/executions")
def get_workflow_executions(workflow_id: str, limit: int = 20):
    return {"success": True, "executions": list_executions(workflow_id=workflow_id, limit=limit)}


# ── Executions Endpoints ──────────────────────────────────────────────────────

@app.get("/api/executions")
def get_all_executions(limit: int = 30):
    return {"success": True, "executions": list_executions(limit=limit)}


@app.get("/api/executions/{execution_id}")
def get_single_execution(execution_id: str):
    rec = get_execution(execution_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return {"success": True, "execution": rec}


@app.post("/api/executions/{execution_id}/approve")
def approve_execution_step(execution_id: str, req: ApprovalDecisionRequest):
    rec = get_execution(execution_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Execution record not found")
    if rec["status"] != "pending_approval":
        raise HTTPException(status_code=400, detail="Execution is not awaiting approval")

    pending_info = rec.get("pending_approval") or {}
    approval_id = pending_info.get("id")
    if not approval_id:
        raise HTTPException(status_code=400, detail="Missing approval reference")

    try:
        res = approve_and_resume_execution(
            execution_id=execution_id,
            approval_id=approval_id,
            decision=req.decision,
        )
        return {"success": True, "execution": res}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/executions/{execution_id}/retry")
def retry_failed_execution(execution_id: str):
    rec = get_execution(execution_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Execution not found")

    try:
        new_exec = execute_workflow(rec["workflow_id"], trigger_type="retry")
        return {"success": True, "execution": new_exec}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Approvals Endpoints ───────────────────────────────────────────────────────

@app.get("/api/approvals")
def get_approvals():
    """Retrieve all pending approvals across all workflows."""
    return {"success": True, "approvals": get_pending_approvals()}


def _confirmation_requested(content: Any) -> bool:
    if isinstance(content, dict):
        return content.get("requires_confirmation") is True
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return False
        return isinstance(decoded, dict) and decoded.get("requires_confirmation") is True
    return False


def _save_pending_confirmations(messages: list[Any]) -> list[dict[str, str]]:
    calls = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                name = call.get("name")
                if name in _CONFIRMATION_TOOL_NAMES:
                    calls[call.get("id")] = call

    confirmations = []
    for message in messages:
        if (
            isinstance(message, ToolMessage)
            and message.tool_call_id in calls
            and _confirmation_requested(message.content)
        ):
            call = calls[message.tool_call_id]
            confirmation_id = uuid.uuid4().hex
            _PENDING_CHAT_CONFIRMATIONS[confirmation_id] = {
                "tool_name": call["name"],
                "arguments": dict(call.get("args") or {}),
                "expires_at": time.monotonic() + 600,
            }
            preview = message.content
            if isinstance(preview, str):
                try:
                    preview = json.loads(preview).get("message", preview)
                except (json.JSONDecodeError, AttributeError):
                    pass
            confirmations.append(
                {"confirmation_id": confirmation_id, "preview": str(preview)}
            )

    while len(_PENDING_CHAT_CONFIRMATIONS) > 100:
        oldest_id = next(iter(_PENDING_CHAT_CONFIRMATIONS))
        _PENDING_CHAT_CONFIRMATIONS.pop(oldest_id)
    return confirmations


# ── Web Chat Endpoint ─────────────────────────────────────────────────────────

@app.post("/api/chat")
def chat_with_agent(req: ChatRequest):
    """
    Process interactive chat message through the LangGraph agent.
    Returns agent reply and detects any confirmation requests.
    """
    messages = []
    # Build prior history
    for item in req.history:
        role = item.get("role", "user")
        content = item.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role in {"assistant", "agent"}:
            messages.append(AIMessage(content=content))

    attachment_text = []
    total_attachment_chars = 0
    if len(req.attachments) > 10:
        raise HTTPException(status_code=400, detail="A chat turn may include at most 10 attachments.")
    for attachment in req.attachments:
        name = attachment.get("name", "").strip()
        content = attachment.get("text", "")
        if not name or not isinstance(content, str):
            raise HTTPException(status_code=400, detail="Each attachment requires a name and text.")
        total_attachment_chars += len(content)
        if total_attachment_chars > MAX_CHAT_ATTACHMENT_TEXT:
            raise HTTPException(
                status_code=413,
                detail="Extracted attachment text exceeds the chat processing limit.",
            )
        attachment_text.append(f"\n\n[Untrusted attachment: {name}]\n{content}")

    # Keep imported file bytes as data in the current turn, not as tool instructions.
    messages.append(HumanMessage(content=req.message + "".join(attachment_text)))

    try:
        result = agent.invoke({"messages": messages})
        output_messages = result.get("messages", [])
        last_message = output_messages[-1] if output_messages else None
        reply_text = str(last_message.content) if last_message else ""
        confirmations = _save_pending_confirmations(output_messages)

        return {
            "success": True,
            "reply": reply_text,
            "requires_confirmation": bool(confirmations),
            "confirmations": confirmations,
        }
    except Exception as exc:
        return {
            "success": False,
            "reply": f"Chat request failed ({type(exc).__name__}).",
            "requires_confirmation": False,
        }


@app.post("/internal/agent/run")
def run_agent_for_backend(req: InternalAgentRunRequest):
    messages = []
    for item in req.history:
        role = item.get("role", "user")
        content = item.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))

    attachment_text = []
    total_attachment_chars = 0
    for attachment in req.attachments:
        name = attachment.get("name", "").strip()
        content = attachment.get("text", "")
        if not name or not isinstance(content, str):
            raise HTTPException(status_code=400, detail="Each attachment requires a name and text.")
        total_attachment_chars += len(content)
        if total_attachment_chars > MAX_CHAT_ATTACHMENT_TEXT:
            raise HTTPException(
                status_code=413,
                detail="Extracted attachment text exceeds the chat processing limit.",
            )
        attachment_text.append(f"\n\n[Untrusted attachment: {name}]\n{content}")

    messages.append(HumanMessage(content=req.message + "".join(attachment_text)))
    result = agent.invoke({"messages": messages})
    output_messages = result.get("messages", [])
    last_message = output_messages[-1] if output_messages else None
    calls = {
        call.get("id"): call
        for item in output_messages
        if isinstance(item, AIMessage)
        for call in item.tool_calls
        if call.get("name") in _CONFIRMATION_TOOL_NAMES
    }
    confirmation_requests = []
    for item in output_messages:
        if not isinstance(item, ToolMessage) or item.tool_call_id not in calls:
            continue
        if not _confirmation_requested(item.content):
            continue
        call = calls[item.tool_call_id]
        preview = item.content
        if isinstance(preview, str):
            try:
                preview = json.loads(preview).get("message", preview)
            except (json.JSONDecodeError, AttributeError):
                pass
        confirmation_requests.append(
            {
                "tool_name": call["name"],
                "arguments": dict(call.get("args") or {}),
                "preview": str(preview),
            }
        )
    return {
        "reply": str(last_message.content) if last_message else "",
        "confirmation_requests": confirmation_requests,
    }


@app.post("/internal/agent/confirm")
def confirm_agent_action(req: InternalAgentConfirmationRequest):
    if req.tool_name not in _CONFIRMATION_TOOL_NAMES:
        raise HTTPException(status_code=400, detail="This action cannot be confirmed through chat.")
    tool = _TOOLS_BY_NAME.get(req.tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail="The requested tool is unavailable.")
    arguments = dict(req.arguments)
    arguments["confirmed"] = True
    try:
        with authorize_tool_call(req.tool_name):
            result = tool.invoke(arguments)
    except (HttpError, FileNotFoundError, PermissionError, ValueError, RuntimeError) as exc:
        raise _drive_http_exception(exc) from exc
    return {"reply": json.dumps(result, ensure_ascii=False, default=str)}


@app.post("/api/chat/confirm")
def confirm_chat_action(req: ChatConfirmationRequest):
    pending = _PENDING_CHAT_CONFIRMATIONS.pop(req.confirmation_id, None)
    if not pending or pending["expires_at"] < time.monotonic():
        raise HTTPException(status_code=404, detail="Confirmation is missing or expired.")

    decision = req.decision.strip().casefold()
    if decision in {"no", "cancel"}:
        return {"success": True, "reply": "The pending Drive action was cancelled."}
    if decision not in {"yes", "confirm"}:
        _PENDING_CHAT_CONFIRMATIONS[req.confirmation_id] = pending
        raise HTTPException(status_code=400, detail="Decision must be yes or no.")

    tool_name = pending["tool_name"]
    tool = _TOOLS_BY_NAME[tool_name]
    arguments = dict(pending["arguments"])
    arguments["confirmed"] = True
    try:
        with authorize_tool_call(tool_name):
            result = tool.invoke(arguments)
    except (HttpError, FileNotFoundError, PermissionError, ValueError, RuntimeError) as exc:
        raise _drive_http_exception(exc) from exc
    return {
        "success": True,
        "reply": json.dumps(result, ensure_ascii=False, default=str),
        "requires_confirmation": False,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
