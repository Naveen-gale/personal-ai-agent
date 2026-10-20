"""Authenticated central API for the independently deployed agent service."""

import logging
import os
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import httpx
import jwt
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app.config import Settings
from backend.app.database import check_mongodb, connect_mongodb
from backend.app.errors import ApiError
from backend.app.schemas import (
    ChatRequest,
    ConfirmationRequest,
    ConversationCreateRequest,
    GoogleSignInRequest,
)
from backend.app.security import create_session_token, require_current_user, verify_google_identity


logger = logging.getLogger("personal_agent.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    app.state.settings = settings
    client, database = await connect_mongodb(settings.mongodb_url, settings.database_name)
    app.state.mongo_client = client
    app.state.database = database
    try:
        yield
    finally:
        await client.close()


app = FastAPI(
    title="Personal AI Agent API",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "FRONTEND_ORIGINS", "http://localhost:5173"
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    supplied_id = request.headers.get("x-request-id", "").strip()
    request_id = (
        supplied_id
        if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", supplied_id)
        else uuid.uuid4().hex
    )
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": exc.code,
                "category": exc.category,
                "message": exc.message,
                "retryable": exc.retryable,
                "details": exc.details,
                "request_id": getattr(request.state, "request_id", None),
            },
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    code = {
        400: "BAD_REQUEST",
        401: "AUTHENTICATION_REQUIRED",
        403: "ACCESS_DENIED",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "REQUEST_TOO_LARGE",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
    }.get(exc.status_code, "REQUEST_FAILED")
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed."
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {
                "code": code,
                "category": "request",
                "message": message,
                "retryable": False,
                "details": None,
                "request_id": getattr(request.state, "request_id", None),
            },
        },
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "category": "request",
                "message": "The request contains invalid or missing fields.",
                "retryable": False,
                "details": [
                    {"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
                    for item in exc.errors()
                ],
                "request_id": getattr(request.state, "request_id", None),
            },
        },
    )


@app.exception_handler(PyMongoError)
async def database_error_handler(request: Request, exc: PyMongoError):
    request_id = getattr(request.state, "request_id", None)
    logger.warning("MongoDB request failure request_id=%s type=%s", request_id, type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={
            "success": False,
            "error": {
                "code": "DATABASE_UNAVAILABLE",
                "category": "dependency",
                "message": "The database could not complete the request.",
                "retryable": True,
                "details": None,
                "request_id": request_id,
            },
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error("Unhandled request failure request_id=%s type=%s", request_id, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "category": "internal",
                "message": "The service could not complete the request.",
                "retryable": False,
                "details": None,
                "request_id": request_id,
            },
        },
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _user_id(user: dict[str, Any]) -> str:
    return str(user["_id"])


def _serialize(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result["id"] = str(result.pop("_id"))
    return result


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "personal-ai-backend", "version": app.version}


@app.get("/api/ready")
async def readiness(request: Request):
    database = getattr(request.app.state, "database", None)
    if database is None or not await check_mongodb(database):
        raise ApiError(
            "DATABASE_UNAVAILABLE",
            "The database is not ready.",
            status_code=503,
            category="dependency",
            retryable=True,
        )
    settings: Settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(timeout=min(settings.agent_timeout_seconds, 5)) as client:
            agent_response = await client.get(
                f"{settings.agent_service_url}/api/health",
                headers={"Authorization": f"Bearer {settings.agent_service_token}"},
            )
    except httpx.HTTPError as exc:
        raise ApiError(
            "AGENT_UNAVAILABLE",
            "The agent service is not ready.",
            status_code=503,
            category="dependency",
            retryable=True,
        ) from exc
    if agent_response.status_code != 200:
        raise ApiError(
            "AGENT_UNAVAILABLE",
            "The agent service is not ready.",
            status_code=503,
            category="dependency",
            retryable=True,
        )
    return {"status": "ready", "database": "ok", "agent": "ok"}


@app.post("/api/v1/auth/google")
async def google_sign_in(payload: GoogleSignInRequest, request: Request):
    settings: Settings = request.app.state.settings
    try:
        identity = await verify_google_identity(payload.credential, settings)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        if isinstance(exc, (ValueError, jwt.InvalidTokenError)):
            raise HTTPException(status_code=401, detail="Google Sign-In credential is invalid or expired.") from exc
        logger.warning("Google identity verification failed type=%s", type(exc).__name__)
        raise ApiError(
            "IDENTITY_PROVIDER_UNAVAILABLE",
            "Google Sign-In could not be verified. Please retry.",
            status_code=503,
            category="dependency",
            retryable=True,
        ) from exc

    user_id = uuid.uuid4().hex
    now = _now()
    try:
        result = await request.app.state.database.users.find_one_and_update(
            {"google_sub": identity["google_sub"]},
            {
                "$setOnInsert": {
                    "_id": user_id,
                    "google_sub": identity["google_sub"],
                    "email": identity["email"],
                    "name": identity["name"],
                    "status": "active",
                    "created_at": now,
                },
                "$set": {"last_login_at": now},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except (DuplicateKeyError, PyMongoError) as exc:
        logger.error("User persistence failed type=%s", type(exc).__name__)
        raise ApiError(
            "USER_STORE_UNAVAILABLE",
            "Your account could not be loaded. Please retry.",
            status_code=503,
            category="dependency",
            retryable=True,
        ) from exc
    token = create_session_token(str(result["_id"]), settings)
    return {
        "success": True,
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": settings.session_ttl_seconds,
        "user": {"id": str(result["_id"]), "email": result["email"], "name": result["name"]},
    }


@app.get("/api/v1/me")
async def current_user(user=Depends(require_current_user)):
    return {
        "success": True,
        "user": {"id": str(user["_id"]), "email": user["email"], "name": user["name"]},
    }


@app.get("/api/v1/conversations")
async def list_conversations(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    user=Depends(require_current_user),
):
    cursor = (
        request.app.state.database.conversations.find({"user_id": _user_id(user)})
        .sort("updated_at", -1)
        .limit(limit)
    )
    conversations = await cursor.to_list(length=limit)
    return {"success": True, "conversations": [_serialize(item) for item in conversations]}


@app.post("/api/v1/conversations")
async def create_conversation(
    payload: ConversationCreateRequest,
    request: Request,
    user=Depends(require_current_user),
):
    now = _now()
    conversation = {
        "_id": uuid.uuid4().hex,
        "user_id": _user_id(user),
        "title": payload.title.strip(),
        "created_at": now,
        "updated_at": now,
    }
    await request.app.state.database.conversations.insert_one(conversation)
    return {"success": True, "conversation": _serialize(conversation)}


@app.get("/api/v1/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=200),
    user=Depends(require_current_user),
):
    database = request.app.state.database
    owner_filter = {"_id": conversation_id, "user_id": _user_id(user)}
    if not await database.conversations.find_one(owner_filter):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    cursor = (
        database.messages.find({"conversation_id": conversation_id, "user_id": _user_id(user)})
        .sort("created_at", 1)
        .limit(limit)
    )
    messages = await cursor.to_list(length=limit)
    return {"success": True, "messages": [_serialize(item) for item in messages]}


@app.delete("/api/v1/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    request: Request,
    user=Depends(require_current_user),
):
    database = request.app.state.database
    owner_filter = {"_id": conversation_id, "user_id": _user_id(user)}
    deleted = await database.conversations.delete_one(owner_filter)
    if not deleted.deleted_count:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    related_filter = {"user_id": _user_id(user), "conversation_id": conversation_id}
    await database.messages.delete_many(related_filter)
    await database.executions.delete_many(related_filter)
    await database.approvals.delete_many(related_filter)
    return {"success": True}


async def _call_agent(request: Request, path: str, payload: dict[str, Any]):
    settings: Settings = request.app.state.settings
    try:
        async with httpx.AsyncClient(timeout=settings.agent_timeout_seconds) as client:
            response = await client.post(
                f"{settings.agent_service_url}{path}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.agent_service_token}",
                    "X-Request-ID": request.state.request_id,
                },
            )
    except httpx.TimeoutException as exc:
        raise ApiError(
            "AGENT_TIMEOUT",
            "The agent took too long to respond. Retry with the same idempotency key.",
            status_code=504,
            category="dependency",
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise ApiError(
            "AGENT_UNAVAILABLE",
            "The agent service is unavailable. Please retry.",
            status_code=503,
            category="dependency",
            retryable=True,
        ) from exc

    if response.status_code == 401:
        raise ApiError(
            "AGENT_SERVICE_AUTH_FAILED",
            "The backend could not authenticate with the agent service.",
            status_code=502,
            category="dependency",
        )
    if response.status_code >= 500:
        raise ApiError(
            "AGENT_REQUEST_FAILED",
            "The agent could not complete the request.",
            status_code=502,
            category="dependency",
            retryable=True,
        )
    if response.status_code >= 400:
        raise ApiError(
            "AGENT_REQUEST_REJECTED",
            "The agent rejected the request.",
            status_code=422,
            category="agent",
            details={"agent_status": response.status_code},
        )
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError(
            "INVALID_AGENT_RESPONSE",
            "The agent returned an invalid response.",
            status_code=502,
            category="dependency",
        ) from exc


@app.post("/api/v1/chat")
async def chat(
    payload: ChatRequest,
    request: Request,
    user=Depends(require_current_user),
):
    database = request.app.state.database
    uid = _user_id(user)
    now = _now()
    existing = await database.executions.find_one(
        {"user_id": uid, "idempotency_key": payload.idempotency_key}
    )
    if existing:
        if payload.conversation_id and existing.get("conversation_id") != payload.conversation_id:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for another conversation.")
        if existing.get("status") in {"completed", "waiting_for_approval"}:
            return {
                "success": True,
                "conversation_id": existing["conversation_id"],
                "execution_id": existing["_id"],
                "reply": existing.get("reply", ""),
                "confirmations": existing.get("confirmations", []),
            }
        raise HTTPException(status_code=409, detail="A request with this idempotency key is already in progress.")

    conversation_id = payload.conversation_id
    new_conversation = None
    if conversation_id:
        conversation = await database.conversations.find_one({"_id": conversation_id, "user_id": uid})
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found.")
    else:
        conversation_id = uuid.uuid4().hex
        title = payload.message.strip().splitlines()[0][:80] or "New conversation"
        new_conversation = {
            "_id": conversation_id,
            "user_id": uid,
            "title": title,
            "created_at": now,
            "updated_at": now,
        }

    execution_id = uuid.uuid4().hex
    try:
        await database.executions.insert_one(
            {
                "_id": execution_id,
                "user_id": uid,
                "conversation_id": conversation_id,
                "idempotency_key": payload.idempotency_key,
                "status": "running",
                "created_at": now,
                "updated_at": now,
            }
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="A request with this idempotency key is already in progress.")

    message_doc = {
        "_id": uuid.uuid4().hex,
        "user_id": uid,
        "conversation_id": conversation_id,
        "execution_id": execution_id,
        "role": "user",
        "content": payload.message,
        "attachments": payload.attachments,
        "created_at": now,
    }
    try:
        if new_conversation:
            await database.conversations.insert_one(new_conversation)
        await database.messages.insert_one(message_doc)
        history_cursor = (
            database.messages.find(
                {
                    "user_id": uid,
                    "conversation_id": conversation_id,
                    "role": {"$in": ["user", "assistant"]},
                }
            )
            .sort("created_at", -1)
            .limit(14)
        )
        history = await history_cursor.to_list(length=14)
        history.reverse()
        history = [
            {"role": item["role"], "content": item["content"]}
            for item in history
            if item["_id"] != message_doc["_id"]
        ]
        agent_result = await _call_agent(
            request,
            "/internal/agent/run",
            {
                "user_id": uid,
                "message": payload.message,
                "history": history,
                "attachments": payload.attachments,
            },
        )
        reply = str(agent_result.get("reply", ""))
        raw_approvals = agent_result.get("confirmation_requests", [])
        confirmations = []
        for approval in raw_approvals:
            confirmation_id = uuid.uuid4().hex
            approval_doc = {
                "_id": confirmation_id,
                "user_id": uid,
                "conversation_id": conversation_id,
                "execution_id": execution_id,
                "tool_name": approval["tool_name"],
                "arguments": approval["arguments"],
                "preview": approval["preview"],
                "status": "pending",
                "created_at": _now(),
            }
            await database.approvals.insert_one(approval_doc)
            confirmations.append(
                {"confirmation_id": confirmation_id, "preview": approval["preview"]}
            )
        status = "waiting_for_approval" if confirmations else "completed"
        completed_at = _now()
        await database.messages.insert_one(
            {
                "_id": uuid.uuid4().hex,
                "user_id": uid,
                "conversation_id": conversation_id,
                "execution_id": execution_id,
                "role": "assistant",
                "content": reply,
                "created_at": completed_at,
            }
        )
        await database.executions.update_one(
            {"_id": execution_id, "user_id": uid},
            {
                "$set": {
                    "status": status,
                    "reply": reply,
                    "confirmations": confirmations,
                    "completed_at": completed_at,
                    "updated_at": completed_at,
                }
            },
        )
        await database.conversations.update_one(
            {"_id": conversation_id, "user_id": uid},
            {"$set": {"updated_at": completed_at}},
        )
    except Exception as exc:
        logger.error(
            "Chat execution failed execution_id=%s type=%s",
            execution_id,
            type(exc).__name__,
        )
        await database.executions.update_one(
            {"_id": execution_id, "user_id": uid},
            {"$set": {"status": "failed", "updated_at": _now()}},
        )
        await database.approvals.delete_many(
            {"execution_id": execution_id, "user_id": uid, "status": "pending"}
        )
        raise

    return {
        "success": True,
        "conversation_id": conversation_id,
        "execution_id": execution_id,
        "reply": reply,
        "confirmations": confirmations,
    }


@app.post("/api/v1/chat/confirm")
async def confirm_chat_action(
    payload: ConfirmationRequest,
    request: Request,
    user=Depends(require_current_user),
):
    decision = payload.decision.strip().casefold()
    if decision not in {"yes", "confirm", "no", "cancel"}:
        raise HTTPException(status_code=400, detail="Decision must be yes or no.")
    database = request.app.state.database
    uid = _user_id(user)
    approval = await database.approvals.find_one(
        {"_id": payload.confirmation_id, "user_id": uid}
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Confirmation is missing or already resolved.")
    approved = decision in {"yes", "confirm"}
    desired_status = "approved" if approved else "rejected"
    if approval.get("status") == desired_status:
        return {"success": True, "reply": approval.get("resolution_reply", "")}
    approval = await database.approvals.find_one_and_update(
        {"_id": payload.confirmation_id, "user_id": uid, "status": "pending"},
        {"$set": {"status": "processing"}},
        return_document=ReturnDocument.BEFORE,
    )
    if not approval:
        raise HTTPException(status_code=409, detail="This confirmation is already being resolved.")
    if approved:
        try:
            result = await _call_agent(
                request,
                "/internal/agent/confirm",
                {
                    "user_id": uid,
                    "tool_name": approval["tool_name"],
                    "arguments": approval["arguments"],
                },
            )
        except Exception as exc:
            await database.approvals.update_one(
                {"_id": approval["_id"], "user_id": uid, "status": "processing"},
                {
                    "$set": {
                        "status": "failed",
                        "resolved_at": _now(),
                        "failure_type": type(exc).__name__,
                    }
                },
            )
            await database.executions.update_one(
                {"_id": approval["execution_id"], "user_id": uid},
                {"$set": {"status": "failed", "updated_at": _now()}},
            )
            raise
        reply = str(result.get("reply", ""))
    else:
        reply = "The pending action was cancelled."
    now = _now()
    await database.approvals.update_one(
        {"_id": approval["_id"], "user_id": uid, "status": "processing"},
        {
            "$set": {
                "status": desired_status,
                "decision": decision,
                "resolution_reply": reply,
                "resolved_at": now,
            }
        },
    )
    await database.messages.insert_one(
        {
            "_id": uuid.uuid4().hex,
            "user_id": uid,
            "conversation_id": approval["conversation_id"],
            "execution_id": approval["execution_id"],
            "role": "assistant",
            "content": reply,
            "created_at": now,
        }
    )
    pending_count = await database.approvals.count_documents(
        {"execution_id": approval["execution_id"], "user_id": uid, "status": "pending"}
    )
    if pending_count == 0:
        await database.executions.update_one(
            {"_id": approval["execution_id"], "user_id": uid},
            {"$set": {"status": "completed", "updated_at": now}},
        )
    return {"success": True, "reply": reply}


@app.get("/api/v1/approvals")
async def list_pending_approvals(request: Request, user=Depends(require_current_user)):
    cursor = (
        request.app.state.database.approvals.find(
            {"user_id": _user_id(user), "status": "pending"}
        )
        .sort("created_at", -1)
        .limit(100)
    )
    approvals = await cursor.to_list(length=100)
    return {
        "success": True,
        "approvals": [
            {
                "confirmation_id": item["_id"],
                "conversation_id": item["conversation_id"],
                "execution_id": item["execution_id"],
                "preview": item["preview"],
                "created_at": item["created_at"],
            }
            for item in approvals
        ],
    }


@app.get("/api/v1/executions")
async def list_executions(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    user=Depends(require_current_user),
):
    cursor = (
        request.app.state.database.executions.find({"user_id": _user_id(user)})
        .sort("created_at", -1)
        .limit(limit)
    )
    executions = await cursor.to_list(length=limit)
    return {
        "success": True,
        "executions": [
            {
                "id": item["_id"],
                "conversation_id": item["conversation_id"],
                "status": item["status"],
                "created_at": item["created_at"],
                "completed_at": item.get("completed_at"),
                "reply": item.get("reply"),
            }
            for item in executions
        ],
    }


@app.get("/api/v1/executions/{execution_id}")
async def get_execution(
    execution_id: str,
    request: Request,
    user=Depends(require_current_user),
):
    execution = await request.app.state.database.executions.find_one(
        {"_id": execution_id, "user_id": _user_id(user)}
    )
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found.")
    return {
        "success": True,
        "execution": {
            "id": execution["_id"],
            "conversation_id": execution["conversation_id"],
            "status": execution["status"],
            "created_at": execution["created_at"],
            "completed_at": execution.get("completed_at"),
            "reply": execution.get("reply"),
            "confirmations": execution.get("confirmations", []),
        },
    }


@app.api_route("/api/{agent_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def authenticated_agent_proxy(
    agent_path: str,
    request: Request,
    _user=Depends(require_current_user),
):
    if agent_path in {"chat", "chat/confirm"}:
        raise HTTPException(
            status_code=410,
            detail="Use the durable /api/v1/chat endpoints instead.",
        )
    settings: Settings = request.app.state.settings
    body = await request.body()
    if len(body) > settings.max_request_body_bytes:
        raise HTTPException(status_code=413, detail="Request body exceeds the configured size limit.")
    url = f"{settings.agent_service_url}/api/{agent_path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"
    headers = {
        "Authorization": f"Bearer {settings.agent_service_token}",
        "X-Request-ID": request.state.request_id,
    }
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    try:
        async with httpx.AsyncClient(timeout=settings.agent_timeout_seconds) as client:
            upstream = await client.request(request.method, url, content=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise ApiError(
            "AGENT_TIMEOUT",
            "The agent took too long to respond.",
            status_code=504,
            category="dependency",
            retryable=True,
        ) from exc
    except httpx.HTTPError as exc:
        raise ApiError(
            "AGENT_UNAVAILABLE",
            "The agent service is unavailable.",
            status_code=503,
            category="dependency",
            retryable=True,
        ) from exc
    response_headers = {}
    for name in ("content-type", "content-disposition", "cache-control"):
        if name in upstream.headers:
            response_headers[name] = upstream.headers[name]
    if upstream.status_code >= 400:
        try:
            error_body = upstream.json()
        except ValueError:
            error_body = {}
        message = error_body.get("detail") or error_body.get("error") or "The agent could not complete the request."
        if not isinstance(message, str):
            message = "The agent could not complete the request."
        return JSONResponse(
            status_code=upstream.status_code,
            content={
                "success": False,
                "detail": message,
                "error": {
                    "code": f"AGENT_HTTP_{upstream.status_code}",
                    "category": "agent",
                    "message": message,
                    "retryable": upstream.status_code >= 500 or upstream.status_code == 429,
                    "details": None,
                    "request_id": request.state.request_id,
                },
            },
            headers={"X-Request-ID": request.state.request_id},
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )
