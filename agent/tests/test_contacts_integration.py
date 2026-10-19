r"""Opt-in, read-only live Google Contacts API verification.

Run from the project root after authorizing:
    $env:RUN_GOOGLE_CONTACTS_INTEGRATION = "1"
    $env:GOOGLE_CONTACTS_TEST_QUERY = "a user-supplied test query"
    .\agent\.venv\Scripts\python.exe -m pytest agent\tests\test_contacts_integration.py -v

Only names are requested from Google, no contact data is printed, and this test
never creates, edits, deletes, calls, or messages anyone.
"""

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_GOOGLE_CONTACTS_INTEGRATION") != "1",
    reason="Set RUN_GOOGLE_CONTACTS_INTEGRATION=1 to opt in to the live Contacts API.",
)


def test_live_contacts_authentication_and_user_query():
    query = os.getenv("GOOGLE_CONTACTS_TEST_QUERY", "").strip()
    if not query:
        pytest.skip("Set GOOGLE_CONTACTS_TEST_QUERY to a query you choose.")

    from agent.services.contacts_service import get_contacts_service, _execute

    people_api = get_contacts_service().people()
    # Google recommends warming the contact search cache with an empty query.
    _execute(people_api.searchContacts(query="", readMask="names", pageSize=1))
    result = _execute(
        people_api.searchContacts(query=query, readMask="names", pageSize=1)
    )

    results = result.get("results", [])
    assert isinstance(results, list)
    assert len(results) <= 1
    assert all(isinstance(item, dict) for item in results)
