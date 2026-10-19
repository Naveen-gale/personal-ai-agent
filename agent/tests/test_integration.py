"""
tests/test_integration.py
--------------------------
Integration tests for the Gmail Personal AI Agent.

These tests attempt to communicate with the real Gmail API using the
saved token in agent/token.json.

If token.json is missing, expired without refresh, or does not have the
required permissions, the tests skip gracefully with a helpful message.

Run with:
    .\\agent\\.venv\\Scripts\\python.exe -m pytest agent\\tests\\test_integration.py -v
"""

import os
import pytest


skip_if_not_enabled = pytest.mark.skipif(
    os.getenv("RUN_GOOGLE_GMAIL_INTEGRATION") != "1",
    reason="Set RUN_GOOGLE_GMAIL_INTEGRATION=1 to opt in to real Gmail API tests.",
)


@skip_if_not_enabled
def test_live_gmail_search_inbox():
    """Live test: query the actual user inbox (read-only query)."""
    from agent.services.gmail_service import search_messages
    results = search_messages(query="in:inbox", max_results=2)
    assert isinstance(results, list)
    # Even if 0 messages, it returns a list without crashing
    if len(results) > 0:
        first = results[0]
        assert "id" in first
        assert "sender" in first
        assert "subject" in first


@skip_if_not_enabled
def test_live_gmail_profile():
    """Live test: verify we can retrieve the authenticated user's email address."""
    from agent.services.gmail_service import create_gmail_client
    client = create_gmail_client()
    profile = client.users().getProfile(userId="me").execute()
    assert "emailAddress" in profile
    assert "@" in profile["emailAddress"]
