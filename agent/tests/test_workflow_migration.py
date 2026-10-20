from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from agent.services import workflow_service
from agent.services.migrate_workflows_to_mongodb import load_legacy_records


def test_legacy_import_reader_preserves_workflows_executions_and_approvals(tmp_path: Path):
    database_path = tmp_path / "legacy.db"
    workflow_service.init_workflow_db(database_path)
    workflow = workflow_service.list_workflows(db_path=database_path)[0]
    execution = workflow_service.create_execution(workflow["id"], db_path=database_path)
    approval = workflow_service.create_approval(
        execution_id=execution["id"],
        workflow_id=workflow["id"],
        step_id="approval-step",
        tool_name="send_email",
        tool_args={"to": "owner@example.com"},
        preview="Send the prepared email?",
        db_path=database_path,
    )

    imported = load_legacy_records(database_path)

    assert len(imported["workflows"]) == 2
    assert len(imported["workflow_executions"]) == 1
    assert len(imported["workflow_approvals"]) == 1
    assert imported["workflows"][0]["_id"] == workflow["id"]
    assert imported["workflow_executions"][0]["_id"] == execution["id"]
    assert imported["workflow_approvals"][0]["_id"] == approval["id"]
    assert imported["workflow_approvals"][0]["tool_args"] == {"to": "owner@example.com"}


class FakeCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, field, direction):
        self.documents.sort(key=lambda item: item.get(field) or "", reverse=direction < 0)
        return self

    def limit(self, count):
        self.documents = self.documents[:count]
        return self

    def __iter__(self):
        return iter(self.documents)


class FakeCollection:
    def __init__(self):
        self.documents = {}

    def create_index(self, *_args, **_kwargs):
        return None

    def find_one(self, query):
        if "_id" in query:
            document = self.documents.get(query["_id"])
            return dict(document) if document else None
        for clause in query.get("$or", []):
            document = self.documents.get(clause.get("_id"))
            if document:
                return dict(document)
        return None

    def find(self, query):
        return FakeCursor(
            dict(document)
            for document in self.documents.values()
            if all(document.get(key) == value for key, value in query.items())
        )

    def replace_one(self, query, document, upsert=False):
        if query["_id"] in self.documents or upsert:
            self.documents[query["_id"]] = dict(document)

    def insert_one(self, document):
        self.documents[document["_id"]] = dict(document)

    def update_one(self, query, update):
        document = self.documents.get(query["_id"])
        if not document:
            return SimpleNamespace(matched_count=0, modified_count=0)
        document.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1, modified_count=1)

    def delete_many(self, query):
        ids = [
            key
            for key, document in self.documents.items()
            if all(document.get(field) == value for field, value in query.items())
        ]
        for key in ids:
            del self.documents[key]

    def delete_one(self, query):
        if query["_id"] in self.documents:
            del self.documents[query["_id"]]


class FakeDatabase:
    def __init__(self):
        self.collections = {}

    def __getattr__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def test_mongodb_workflow_service_paths_do_not_use_sqlite(monkeypatch):
    monkeypatch.setenv("WORKFLOW_STORAGE", "mongodb")
    database = FakeDatabase()
    with (
        patch.object(workflow_service, "initialize_mongodb_workflow_store", return_value=database),
        patch.object(workflow_service, "get_mongodb_database", return_value=database),
        patch.object(
            workflow_service,
            "get_db_connection",
            side_effect=AssertionError("MongoDB mode must not open SQLite."),
        ),
    ):
        workflow = workflow_service.save_workflow(
            {
                "id": "workflow-1",
                "name": "Mongo workflow",
                "steps": [{"id": "step-1", "tool": "get_today_events", "inputs": {}}],
            }
        )
        execution = workflow_service.create_execution(workflow["id"])
        completed = workflow_service.update_execution(
            execution["id"],
            status="completed",
            step_results={"step-1": {"output": {"count": 1}}},
        )
        approval = workflow_service.create_approval(
            execution_id=execution["id"],
            workflow_id=workflow["id"],
            step_id="step-2",
            tool_name="send_email",
            tool_args={"to": "owner@example.com"},
            preview="Send the prepared email?",
        )

        assert workflow_service.get_workflow("workflow-1")["name"] == "Mongo workflow"
        assert completed["step_results"]["step-1"]["output"]["count"] == 1
        assert workflow_service.get_pending_approvals()[0]["id"] == approval["id"]
        assert workflow_service.resolve_approval(approval["id"], "approved")["status"] == "approved"
        assert workflow_service.delete_workflow("workflow-1") is True
