"""MongoDB workflow persistence with SQLite compatibility for migration and tests."""

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pymongo import MongoClient
from agent.services.date_utils import to_utc_iso


_AGENT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW_DB_PATH = Path(
    os.getenv("WORKFLOW_DB_PATH", str(_AGENT_DIR / "workflows.db"))
)
WORKFLOW_MIGRATION_ID = "sqlite-workflows-v1"
_MONGO_CLIENTS: dict[str, MongoClient] = {}
_MONGO_INITIALIZED: set[tuple[str, str]] = set()


def uses_mongodb(db_path: Path | str | None = None) -> bool:
    return db_path is None and os.getenv("WORKFLOW_STORAGE", "sqlite").casefold() == "mongodb"


def get_mongodb_database():
    url = os.getenv("WORKFLOW_MONGODB_URL", "").strip()
    database_name = os.getenv("DATABASE_NAME", "personal_agent").strip()
    if not url:
        raise RuntimeError("WORKFLOW_MONGODB_URL is required when WORKFLOW_STORAGE=mongodb.")
    client = _MONGO_CLIENTS.get(url)
    if client is None:
        client = MongoClient(url, serverSelectionTimeoutMS=5000)
        _MONGO_CLIENTS[url] = client
    return client[database_name]


def initialize_mongodb_workflow_store(require_migration: bool = True):
    database = get_mongodb_database()
    key = (
        os.getenv("WORKFLOW_MONGODB_URL", "").strip(),
        os.getenv("DATABASE_NAME", "personal_agent").strip(),
    )
    if key not in _MONGO_INITIALIZED:
        database.workflows.create_index([("status", 1), ("trigger_type", 1), ("next_run_utc", 1)])
        database.workflow_executions.create_index([("workflow_id", 1), ("started_at", -1)])
        database.workflow_approvals.create_index([("status", 1), ("created_at", -1)])
        _MONGO_INITIALIZED.add(key)
    if require_migration:
        marker = database.workflow_migrations.find_one(
            {"_id": WORKFLOW_MIGRATION_ID, "status": "completed"}
        )
        if not marker:
            raise RuntimeError(
                "Workflow MongoDB migration is incomplete. Run "
                "python -m agent.services.migrate_workflows_to_mongodb before starting the agent."
            )
    return database


def get_db_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open the legacy or test SQLite database with row factory and WAL mode."""
    if uses_mongodb(db_path):
        raise RuntimeError("SQLite connection requested while MongoDB is the workflow source of truth.")
    path = Path(db_path) if db_path else DEFAULT_WORKFLOW_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_workflow_db(db_path: Path | str | None = None) -> None:
    """Initialize workflow tables, indices, and seed default workflows if empty."""
    if uses_mongodb(db_path):
        initialize_mongodb_workflow_store()
        return
    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                trigger_type TEXT NOT NULL DEFAULT 'manual',
                trigger_config TEXT NOT NULL DEFAULT '{}',
                steps TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'active',
                next_run_utc TEXT,
                last_run_utc TEXT,
                last_run_status TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_workflows_sched
            ON workflows(status, trigger_type, next_run_utc);
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_executions (
                id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                workflow_name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                current_step_index INTEGER NOT NULL DEFAULT 0,
                step_results TEXT NOT NULL DEFAULT '{}',
                pending_approval TEXT,
                error_message TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_executions_wf
            ON workflow_executions(workflow_id, started_at);
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_approvals (
                id TEXT PRIMARY KEY,
                execution_id TEXT NOT NULL,
                workflow_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_args TEXT NOT NULL,
                preview TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                FOREIGN KEY (execution_id) REFERENCES workflow_executions(id) ON DELETE CASCADE
            );
            """
        )

        # Seed initial default templates if empty
        row = conn.execute("SELECT COUNT(*) AS count FROM workflows").fetchone()
        if row["count"] == 0:
            _seed_default_workflows(conn)

    conn.close()


def _seed_default_workflows(conn: sqlite3.Connection) -> None:
    """Seed useful workflow templates on initial launch."""
    now_utc = to_utc_iso(datetime.now(timezone.utc))

    morning_steps = [
        {"id": "step_1", "name": "Get unread emails", "tool": "get_unread_emails", "inputs": {"max_results": 5}},
        {"id": "step_2", "name": "Get today's calendar", "tool": "get_today_events", "inputs": {"time_zone": "Asia/Kolkata"}},
        {"id": "step_3", "name": "Get pending tasks", "tool": "list_pending_tasks", "inputs": {"max_results": 10}},
        {
            "id": "step_4",
            "name": "Synthesize Morning Briefing",
            "tool": "llm_synthesize",
            "inputs": {
                "prompt": "Create an executive morning briefing highlighting urgent unread emails, today's schedule, and pending priorities.",
                "context_data": "{{all_outputs}}",
            },
        },
    ]

    evening_steps = [
        {"id": "step_1", "name": "Get pending tasks", "tool": "list_pending_tasks", "inputs": {"max_results": 15}},
        {"id": "step_2", "name": "Get tomorrow's schedule", "tool": "list_calendar_events", "inputs": {"start_time": "tomorrow", "max_results": 5}},
        {
            "id": "step_3",
            "name": "Plan Tomorrow",
            "tool": "llm_synthesize",
            "inputs": {
                "prompt": "Review remaining tasks and tomorrow's calendar to recommend a prioritized to-do list and study schedule for tomorrow.",
                "context_data": "{{all_outputs}}",
            },
        },
    ]

    conn.execute(
        """
        INSERT INTO workflows (
            id, name, description, trigger_type, trigger_config, steps,
            status, next_run_utc, last_run_utc, last_run_status, created_at, updated_at
        ) VALUES (
            'wf_morning_overview',
            'Morning Daily Overview',
            'Summarizes unread emails, today calendar schedule, and pending tasks every morning.',
            'scheduled',
            '{"recurrence": "daily", "time": "08:00", "timezone": "Asia/Kolkata"}',
            ?,
            'active',
            NULL, NULL, NULL, ?, ?
        );
        """,
        (json.dumps(morning_steps), now_utc, now_utc),
    )

    conn.execute(
        """
        INSERT INTO workflows (
            id, name, description, trigger_type, trigger_config, steps,
            status, next_run_utc, last_run_utc, last_run_status, created_at, updated_at
        ) VALUES (
            'wf_evening_planner',
            'Evening Daily Review & Planner',
            'Reviews pending tasks and tomorrow schedule every evening to prepare tomorrow plan.',
            'scheduled',
            '{"recurrence": "daily", "time": "19:00", "timezone": "Asia/Kolkata"}',
            ?,
            'active',
            NULL, NULL, NULL, ?, ?
        );
        """,
        (json.dumps(evening_steps), now_utc, now_utc),
    )


# ── Workflow CRUD Operations ──────────────────────────────────────────────────

def save_workflow(workflow_data: dict[str, Any], db_path: Path | str | None = None) -> dict[str, Any]:
    """Create or update a workflow definition."""
    init_workflow_db(db_path)
    wf_id = workflow_data.get("id") or f"wf_{uuid.uuid4().hex[:10]}"
    name = (workflow_data.get("name") or "").strip()
    if not name:
        raise ValueError("Workflow name is required.")

    description = (workflow_data.get("description") or "").strip()
    trigger_type = workflow_data.get("trigger_type") or "manual"
    trigger_config = workflow_data.get("trigger_config") or {}
    steps = workflow_data.get("steps") or []
    status = workflow_data.get("status") or "active"

    now_utc = to_utc_iso(datetime.now(timezone.utc))
    next_run_utc = workflow_data.get("next_run_utc")

    if uses_mongodb(db_path):
        database = initialize_mongodb_workflow_store()
        existing = database.workflows.find_one({"_id": wf_id})
        document = {
            "_id": wf_id,
            "name": name,
            "description": description,
            "trigger_type": trigger_type,
            "trigger_config": trigger_config,
            "steps": steps,
            "status": status,
            "next_run_utc": next_run_utc,
            "last_run_utc": (
                workflow_data.get("last_run_utc")
                if "last_run_utc" in workflow_data
                else (existing.get("last_run_utc") if existing else None)
            ),
            "last_run_status": (
                workflow_data.get("last_run_status")
                if "last_run_status" in workflow_data
                else (existing.get("last_run_status") if existing else None)
            ),
            "created_at": existing["created_at"] if existing else now_utc,
            "updated_at": now_utc,
        }
        database.workflows.replace_one({"_id": wf_id}, document, upsert=True)
        return get_workflow(wf_id, db_path=db_path)  # type: ignore

    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO workflows (
                id, name, description, trigger_type, trigger_config, steps,
                status, next_run_utc, last_run_utc, last_run_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                trigger_type = excluded.trigger_type,
                trigger_config = excluded.trigger_config,
                steps = excluded.steps,
                status = excluded.status,
                next_run_utc = excluded.next_run_utc,
                updated_at = excluded.updated_at;
            """,
            (
                wf_id,
                name,
                description,
                trigger_type,
                json.dumps(trigger_config),
                json.dumps(steps),
                status,
                next_run_utc,
                now_utc,
                now_utc,
            ),
        )
    conn.close()
    return get_workflow(wf_id, db_path=db_path)  # type: ignore


def get_workflow(workflow_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Retrieve a single workflow by ID or Name."""
    init_workflow_db(db_path)
    if uses_mongodb(db_path):
        database = get_mongodb_database()
        document = database.workflows.find_one(
            {
                "$or": [
                    {"_id": workflow_id},
                    {"name": {"$regex": f"^{re.escape(workflow_id)}$", "$options": "i"}},
                ]
            }
        )
        if not document:
            return None
        document["id"] = str(document.pop("_id"))
        return document

    conn = get_db_connection(db_path)
    row = conn.execute(
        "SELECT * FROM workflows WHERE id = ? OR LOWER(name) = LOWER(?)",
        (workflow_id, workflow_id),
    ).fetchone()
    conn.close()
    if not row:
        return None

    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "trigger_type": row["trigger_type"],
        "trigger_config": json.loads(row["trigger_config"]),
        "steps": json.loads(row["steps"]),
        "status": row["status"],
        "next_run_utc": row["next_run_utc"],
        "last_run_utc": row["last_run_utc"],
        "last_run_status": row["last_run_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_workflows(status: str | None = None, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """List workflows with optional status filtering."""
    init_workflow_db(db_path)
    if uses_mongodb(db_path):
        query = {} if not status or status == "all" else {"status": status}
        documents = get_mongodb_database().workflows.find(query).sort("created_at", -1)
        result = []
        for document in documents:
            document["id"] = str(document.pop("_id"))
            result.append(document)
        return result

    conn = get_db_connection(db_path)
    query = "SELECT * FROM workflows"
    params: list[Any] = []
    if status and status != "all":
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()

    result = []
    for r in rows:
        result.append(
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "trigger_type": r["trigger_type"],
                "trigger_config": json.loads(r["trigger_config"]),
                "steps": json.loads(r["steps"]),
                "status": r["status"],
                "next_run_utc": r["next_run_utc"],
                "last_run_utc": r["last_run_utc"],
                "last_run_status": r["last_run_status"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
        )
    return result


def update_workflow_status(
    workflow_id: str, new_status: str, db_path: Path | str | None = None
) -> dict[str, Any]:
    """Enable, pause, or draft a workflow."""
    init_workflow_db(db_path)
    wf = get_workflow(workflow_id, db_path=db_path)
    if not wf:
        raise ValueError(f"Workflow '{workflow_id}' not found.")

    now_utc = to_utc_iso(datetime.now(timezone.utc))
    if uses_mongodb(db_path):
        get_mongodb_database().workflows.update_one(
            {"_id": wf["id"]},
            {"$set": {"status": new_status, "updated_at": now_utc}},
        )
        return get_workflow(wf["id"], db_path=db_path)  # type: ignore

    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE workflows SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now_utc, wf["id"]),
        )
    conn.close()
    return get_workflow(wf["id"], db_path=db_path)  # type: ignore


def delete_workflow(workflow_id: str, db_path: Path | str | None = None) -> bool:
    """Delete a workflow and cascade its executions."""
    init_workflow_db(db_path)
    wf = get_workflow(workflow_id, db_path=db_path)
    if not wf:
        return False

    if uses_mongodb(db_path):
        database = get_mongodb_database()
        database.workflow_approvals.delete_many({"workflow_id": wf["id"]})
        database.workflow_executions.delete_many({"workflow_id": wf["id"]})
        database.workflows.delete_one({"_id": wf["id"]})
        return True

    conn = get_db_connection(db_path)
    with conn:
        conn.execute("DELETE FROM workflows WHERE id = ?", (wf["id"],))
    conn.close()
    return True


# ── Execution History Operations ──────────────────────────────────────────────

def create_execution(
    workflow_id: str, trigger_type: str = "manual", db_path: Path | str | None = None
) -> dict[str, Any]:
    """Initialize a new workflow execution run."""
    init_workflow_db(db_path)
    wf = get_workflow(workflow_id, db_path=db_path)
    if not wf:
        raise ValueError(f"Workflow '{workflow_id}' not found.")

    exec_id = f"exec_{uuid.uuid4().hex[:12]}"
    now_utc = to_utc_iso(datetime.now(timezone.utc))

    if uses_mongodb(db_path):
        database = get_mongodb_database()
        database.workflow_executions.insert_one(
            {
                "_id": exec_id,
                "workflow_id": wf["id"],
                "workflow_name": wf["name"],
                "trigger_type": trigger_type,
                "status": "running",
                "current_step_index": 0,
                "step_results": {},
                "pending_approval": None,
                "error_message": None,
                "started_at": now_utc,
                "completed_at": None,
            }
        )
        database.workflows.update_one(
            {"_id": wf["id"]},
            {"$set": {"last_run_utc": now_utc, "last_run_status": "running"}},
        )
        return get_execution(exec_id, db_path=db_path)  # type: ignore

    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO workflow_executions (
                id, workflow_id, workflow_name, trigger_type, status,
                current_step_index, step_results, pending_approval,
                error_message, started_at, completed_at
            ) VALUES (?, ?, ?, ?, 'running', 0, '{}', NULL, NULL, ?, NULL);
            """,
            (exec_id, wf["id"], wf["name"], trigger_type, now_utc),
        )
        conn.execute(
            "UPDATE workflows SET last_run_utc = ?, last_run_status = 'running' WHERE id = ?",
            (now_utc, wf["id"]),
        )
    conn.close()
    return get_execution(exec_id, db_path=db_path)  # type: ignore


def get_execution(execution_id: str, db_path: Path | str | None = None) -> dict[str, Any] | None:
    """Retrieve an execution run by ID."""
    init_workflow_db(db_path)
    if uses_mongodb(db_path):
        document = get_mongodb_database().workflow_executions.find_one({"_id": execution_id})
        if not document:
            return None
        document["id"] = str(document.pop("_id"))
        return document

    conn = get_db_connection(db_path)
    row = conn.execute(
        "SELECT * FROM workflow_executions WHERE id = ?", (execution_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None

    return {
        "id": row["id"],
        "workflow_id": row["workflow_id"],
        "workflow_name": row["workflow_name"],
        "trigger_type": row["trigger_type"],
        "status": row["status"],
        "current_step_index": row["current_step_index"],
        "step_results": json.loads(row["step_results"]),
        "pending_approval": json.loads(row["pending_approval"]) if row["pending_approval"] else None,
        "error_message": row["error_message"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }


def list_executions(
    workflow_id: str | None = None, limit: int = 20, db_path: Path | str | None = None
) -> list[dict[str, Any]]:
    """List recent execution records."""
    init_workflow_db(db_path)
    if uses_mongodb(db_path):
        query = {"workflow_id": workflow_id} if workflow_id else {}
        documents = (
            get_mongodb_database()
            .workflow_executions.find(query)
            .sort("started_at", -1)
            .limit(min(max(1, limit), 100))
        )
        result = []
        for document in documents:
            document["id"] = str(document.pop("_id"))
            result.append(document)
        return result

    conn = get_db_connection(db_path)
    query = "SELECT * FROM workflow_executions"
    params: list[Any] = []
    if workflow_id:
        query += " WHERE workflow_id = ?"
        params.append(workflow_id)
    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(min(max(1, limit), 100))

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [
        {
            "id": r["id"],
            "workflow_id": r["workflow_id"],
            "workflow_name": r["workflow_name"],
            "trigger_type": r["trigger_type"],
            "status": r["status"],
            "current_step_index": r["current_step_index"],
            "step_results": json.loads(r["step_results"]),
            "pending_approval": json.loads(r["pending_approval"]) if r["pending_approval"] else None,
            "error_message": r["error_message"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
        }
        for r in rows
    ]


def update_execution(
    execution_id: str,
    status: str,
    step_results: dict[str, Any] | None = None,
    current_step_index: int | None = None,
    pending_approval: dict[str, Any] | None = None,
    error_message: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Update execution progress, results, and status."""
    init_workflow_db(db_path)
    now_utc = to_utc_iso(datetime.now(timezone.utc)) if status in {"completed", "failed", "cancelled"} else None

    if uses_mongodb(db_path):
        database = get_mongodb_database()
        execution = database.workflow_executions.find_one({"_id": execution_id})
        if not execution:
            raise ValueError(f"Execution '{execution_id}' not found.")
        merged_results = dict(execution.get("step_results") or {})
        if step_results:
            merged_results.update(step_results)
        updates = {
            "status": status,
            "current_step_index": (
                current_step_index
                if current_step_index is not None
                else execution.get("current_step_index", 0)
            ),
            "step_results": merged_results,
            "pending_approval": pending_approval,
            "error_message": error_message,
        }
        if now_utc:
            updates["completed_at"] = now_utc
        database.workflow_executions.update_one(
            {"_id": execution_id},
            {"$set": updates},
        )
        database.workflows.update_one(
            {"_id": execution["workflow_id"]},
            {"$set": {"last_run_status": status}},
        )
        return get_execution(execution_id, db_path=db_path)  # type: ignore

    conn = get_db_connection(db_path)
    exec_row = conn.execute("SELECT * FROM workflow_executions WHERE id = ?", (execution_id,)).fetchone()
    if not exec_row:
        conn.close()
        raise ValueError(f"Execution '{execution_id}' not found.")

    merged_results = json.loads(exec_row["step_results"])
    if step_results:
        merged_results.update(step_results)

    idx = current_step_index if current_step_index is not None else exec_row["current_step_index"]

    with conn:
        conn.execute(
            """
            UPDATE workflow_executions
            SET status = ?, current_step_index = ?, step_results = ?,
                pending_approval = ?, error_message = ?, completed_at = COALESCE(?, completed_at)
            WHERE id = ?;
            """,
            (
                status,
                idx,
                json.dumps(merged_results),
                json.dumps(pending_approval) if pending_approval else None,
                error_message,
                now_utc,
                execution_id,
            ),
        )
        # Update parent workflow status
        conn.execute(
            "UPDATE workflows SET last_run_status = ? WHERE id = ?",
            (status, exec_row["workflow_id"]),
        )
    conn.close()
    return get_execution(execution_id, db_path=db_path)  # type: ignore


# ── Approvals Operations ──────────────────────────────────────────────────────

def create_approval(
    execution_id: str,
    workflow_id: str,
    step_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    preview: str,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Create a pending human approval record."""
    init_workflow_db(db_path)
    approval_id = f"appr_{uuid.uuid4().hex[:10]}"
    now_utc = to_utc_iso(datetime.now(timezone.utc))

    if uses_mongodb(db_path):
        document = {
            "_id": approval_id,
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "step_id": step_id,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "preview": preview,
            "status": "pending",
            "created_at": now_utc,
            "resolved_at": None,
        }
        get_mongodb_database().workflow_approvals.insert_one(document)
        document["id"] = str(document.pop("_id"))
        return document

    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO workflow_approvals (
                id, execution_id, workflow_id, step_id, tool_name,
                tool_args, preview, status, created_at, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, NULL);
            """,
            (
                approval_id,
                execution_id,
                workflow_id,
                step_id,
                tool_name,
                json.dumps(tool_args),
                preview,
                now_utc,
            ),
        )
    conn.close()
    return {
        "id": approval_id,
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        "step_id": step_id,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "preview": preview,
        "status": "pending",
        "created_at": now_utc,
    }


def get_pending_approvals(db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """Retrieve all approvals currently waiting for user decision."""
    init_workflow_db(db_path)
    if uses_mongodb(db_path):
        documents = (
            get_mongodb_database()
            .workflow_approvals.find({"status": "pending"})
            .sort("created_at", -1)
        )
        result = []
        for document in documents:
            document["id"] = str(document.pop("_id"))
            result.append(document)
        return result

    conn = get_db_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM workflow_approvals WHERE status = 'pending' ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    return [
        {
            "id": r["id"],
            "execution_id": r["execution_id"],
            "workflow_id": r["workflow_id"],
            "step_id": r["step_id"],
            "tool_name": r["tool_name"],
            "tool_args": json.loads(r["tool_args"]),
            "preview": r["preview"],
            "status": r["status"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def resolve_approval(
    approval_id: str, decision: str, db_path: Path | str | None = None
) -> dict[str, Any]:
    """Mark an approval as 'approved' or 'rejected'."""
    init_workflow_db(db_path)
    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be either 'approved' or 'rejected'.")

    now_utc = to_utc_iso(datetime.now(timezone.utc))
    if uses_mongodb(db_path):
        database = get_mongodb_database()
        database.workflow_approvals.update_one(
            {"_id": approval_id},
            {"$set": {"status": decision, "resolved_at": now_utc}},
        )
        document = database.workflow_approvals.find_one({"_id": approval_id})
        if not document:
            raise ValueError(f"Approval '{approval_id}' not found.")
        return {
            "id": str(document["_id"]),
            "execution_id": document["execution_id"],
            "workflow_id": document["workflow_id"],
            "step_id": document["step_id"],
            "tool_name": document["tool_name"],
            "status": document["status"],
            "resolved_at": document["resolved_at"],
        }

    conn = get_db_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE workflow_approvals SET status = ?, resolved_at = ? WHERE id = ?",
            (decision, now_utc, approval_id),
        )
    row = conn.execute("SELECT * FROM workflow_approvals WHERE id = ?", (approval_id,)).fetchone()
    conn.close()

    if not row:
        raise ValueError(f"Approval '{approval_id}' not found.")

    return {
        "id": row["id"],
        "execution_id": row["execution_id"],
        "workflow_id": row["workflow_id"],
        "step_id": row["step_id"],
        "tool_name": row["tool_name"],
        "status": row["status"],
        "resolved_at": row["resolved_at"],
    }
