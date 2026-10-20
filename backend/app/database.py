"""Async MongoDB lifecycle and schema indexes."""

from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError


async def connect_mongodb(url: str, database_name: str):
    client = AsyncMongoClient(url, serverSelectionTimeoutMS=5000)
    try:
        await client.admin.command("ping")
        database = client[database_name]
        await database.users.create_index("google_sub", unique=True)
        await database.users.create_index("email", unique=True)
        await database.conversations.create_index([("user_id", 1), ("updated_at", -1)])
        await database.messages.create_index(
            [("user_id", 1), ("conversation_id", 1), ("created_at", 1)]
        )
        await database.executions.create_index(
            [("user_id", 1), ("idempotency_key", 1)],
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string"}},
        )
        await database.executions.create_index([("user_id", 1), ("created_at", -1)])
        await database.approvals.create_index([("user_id", 1), ("status", 1), ("created_at", -1)])
        return client, database
    except Exception:
        await client.close()
        raise


async def check_mongodb(database) -> bool:
    try:
        await database.command("ping")
        return True
    except PyMongoError:
        return False
