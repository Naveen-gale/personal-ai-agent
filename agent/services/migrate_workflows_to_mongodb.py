"""Non-destructive one-time import of SQLite workflows into MongoDB."""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from agent.services.workflow_service import (
    DEFAULT_WORKFLOW_DB_PATH,
    WORKFLOW_MIGRATION_ID,
    initialize_mongodb_workflow_store,
)


def _decode_json(value: str | None, default: Any, field: str) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"SQLite workflow data contains invalid JSON in '{field}'.") from exc


def load_legacy_records(sqlite_path: Path | str) -> dict[str, list[dict[str, Any]]]:
    """Read all existing workflow records without modifying the SQLite file."""
    source = Path(sqlite_path)
    if not source.is_file():
        raise FileNotFoundError(f"Legacy workflow database does not exist: {source}")

    connection = sqlite3.connect(str(source.resolve()))
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only = ON")
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        required = {"workflows", "workflow_executions", "workflow_approvals"}
        missing = required - tables
        if missing:
            raise ValueError(f"Legacy workflow database is missing tables: {', '.join(sorted(missing))}")

        workflows = []
        for row in connection.execute("SELECT * FROM workflows").fetchall():
            item = dict(row)
            item["_id"] = item.pop("id")
            item["trigger_config"] = _decode_json(
                item["trigger_config"], {}, "workflows.trigger_config"
            )
            item["steps"] = _decode_json(item["steps"], [], "workflows.steps")
            workflows.append(item)

        executions = []
        for row in connection.execute("SELECT * FROM workflow_executions").fetchall():
            item = dict(row)
            item["_id"] = item.pop("id")
            item["step_results"] = _decode_json(
                item["step_results"], {}, "workflow_executions.step_results"
            )
            item["pending_approval"] = _decode_json(
                item["pending_approval"], None, "workflow_executions.pending_approval"
            )
            executions.append(item)

        approvals = []
        for row in connection.execute("SELECT * FROM workflow_approvals").fetchall():
            item = dict(row)
            item["_id"] = item.pop("id")
            item["tool_args"] = _decode_json(
                item["tool_args"], {}, "workflow_approvals.tool_args"
            )
            approvals.append(item)
        return {
            "workflows": workflows,
            "workflow_executions": executions,
            "workflow_approvals": approvals,
        }
    finally:
        connection.close()


def migrate_workflows(sqlite_path: Path | str = DEFAULT_WORKFLOW_DB_PATH) -> dict[str, int]:
    source = Path(sqlite_path).resolve()
    records = load_legacy_records(source)
    database = initialize_mongodb_workflow_store(require_migration=False)
    marker = database.workflow_migrations.find_one({"_id": WORKFLOW_MIGRATION_ID})
    if marker and marker.get("status") == "completed":
        if marker.get("source") != str(source):
            raise RuntimeError(
                "Workflow migration was already completed from a different SQLite source."
            )
        return marker["source_counts"]
    if marker and marker.get("source") != str(source):
        raise RuntimeError(
            "An incomplete workflow migration exists for a different SQLite source."
        )
    if not marker:
        collection_names = ("workflows", "workflow_executions", "workflow_approvals")
        if any(database[name].count_documents({}) for name in collection_names):
            raise RuntimeError(
                "Target workflow collections are not empty. Refusing to merge or overwrite existing data."
            )
        database.workflow_migrations.insert_one(
            {"_id": WORKFLOW_MIGRATION_ID, "status": "in_progress", "source": str(source)}
        )

    counts = {name: len(items) for name, items in records.items()}
    for collection_name, items in records.items():
        collection = database[collection_name]
        for item in items:
            record_id = item["_id"]
            collection.update_one(
                {"_id": record_id},
                {"$setOnInsert": item},
                upsert=True,
            )
    database.workflow_migrations.update_one(
        {"_id": WORKFLOW_MIGRATION_ID},
        {
            "$set": {
                "status": "completed",
                "source_counts": counts,
            }
        },
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=DEFAULT_WORKFLOW_DB_PATH,
        help="Existing SQLite workflow database to import (read-only).",
    )
    args = parser.parse_args()
    counts = migrate_workflows(args.sqlite_path)
    print(
        "Workflow import complete: "
        + ", ".join(f"{collection}={count}" for collection, count in counts.items())
    )


if __name__ == "__main__":
    main()
