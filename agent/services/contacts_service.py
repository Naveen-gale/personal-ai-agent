"""Google People API operations for the agent's Google Contacts."""

import re
from collections.abc import Mapping
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from agent.auth.gmail_auth import CONTACTS_SCOPES, AGENT_DIR, get_credentials


TOKEN_FILE = AGENT_DIR / "token.json"
CONTACT_FIELDS = "names,phoneNumbers,emailAddresses"
MAX_RESULTS = 50


def get_contacts_service() -> Any:
    """Build the People API client using the shared Google OAuth token."""
    credentials = get_credentials(required_scopes=CONTACTS_SCOPES)
    return build("people", "v1", credentials=credentials, cache_discovery=False)


def _execute(request: Any) -> dict[str, Any]:
    """Execute an API request while keeping Google response bodies out of errors."""
    try:
        response = request.execute()
    except HttpError as error:
        status = getattr(error.resp, "status", "unknown")
        raise RuntimeError(
            f"Google Contacts API request failed (HTTP {status}). "
            "Check that the People API is enabled and the OAuth grant is valid."
        ) from error
    except Exception as error:
        raise RuntimeError(
            "Google Contacts API request failed "
            f"({type(error).__name__}). Check network connectivity and API access."
        ) from error
    if not isinstance(response, Mapping):
        raise RuntimeError("Google Contacts API returned an invalid response.")
    return dict(response)


def _all_contacts() -> list[dict[str, Any]]:
    """Return all connections, following every People API page."""
    service = get_contacts_service()
    contacts: list[dict[str, Any]] = []
    page_token: str | None = None

    while True:
        params: dict[str, Any] = {
            "resourceName": "people/me",
            "personFields": CONTACT_FIELDS,
            "pageSize": 1000,
        }
        if page_token:
            params["pageToken"] = page_token
        response = _execute(service.people().connections().list(**params))

        page = response.get("connections", [])
        if not isinstance(page, list) or any(
            not isinstance(person, Mapping) for person in page
        ):
            raise RuntimeError("Google Contacts API returned malformed contacts.")
        contacts.extend(dict(person) for person in page)

        page_token = response.get("nextPageToken")
        if not page_token:
            return contacts


def _format_contact(person: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a People API person object into a stable, privacy-conscious shape."""
    names = person.get("names", [])
    phones = person.get("phoneNumbers", [])
    emails = person.get("emailAddresses", [])
    name = "Unknown"

    if isinstance(names, list) and names and isinstance(names[0], Mapping):
        first_name = names[0].get("displayName")
        if not first_name:
            first_name = " ".join(
                str(names[0].get(part, "")).strip()
                for part in ("givenName", "middleName", "familyName")
                if names[0].get(part)
            )
        name = first_name or "Unknown"

    return {
        "name": str(name),
        "phone_numbers": _field_values(phones),
        "emails": _field_values(emails),
    }


def _field_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [
        str(item["value"])
        for item in values
        if isinstance(item, Mapping) and item.get("value")
    ]


def _unique_contacts(people: list[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()

    for person in people:
        contact = _format_contact(person)
        resource_name = person.get("resourceName")
        key = str(resource_name) if resource_name else repr(contact)
        if key in seen:
            continue
        seen.add(key)
        matches.append(contact)
        if len(matches) >= limit:
            break
    return matches


def _search_names(query: str, limit: int) -> list[dict[str, Any]]:
    """Use searchContacts for name queries and warm its cache before searching."""
    service = get_contacts_service()
    people_api = service.people()
    _execute(
        people_api.searchContacts(
            query="",
            readMask=CONTACT_FIELDS,
            pageSize=min(limit, 30),
        )
    )

    people: list[Mapping[str, Any]] = []
    page_token: str | None = None
    while len(_unique_contacts(people, limit)) < limit:
        remaining = limit - len(_unique_contacts(people, limit))
        params: dict[str, Any] = {
            "query": query,
            "readMask": CONTACT_FIELDS,
            "pageSize": min(remaining, 30),
        }
        if page_token:
            params["pageToken"] = page_token
        response = _execute(people_api.searchContacts(**params))
        results = response.get("results", [])
        if not isinstance(results, list):
            raise RuntimeError("Google Contacts API returned malformed search results.")

        for result in results:
            if not isinstance(result, Mapping):
                raise RuntimeError("Google Contacts API returned malformed search results.")
            person = result.get("person")
            if not isinstance(person, Mapping):
                raise RuntimeError("Google Contacts API returned malformed search results.")
            people.append(person)

        page_token = response.get("nextPageToken")
        if not page_token or not results:
            break
    return _unique_contacts(people, limit)


def _is_phone_query(query: str) -> bool:
    return bool(query) and bool(re.fullmatch(r"[+\d().\-\s]+", query))


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def search_contacts(query: str, limit: int = 10) -> dict[str, Any]:
    """Search names with People API and phone-number substrings locally."""
    normalized_query = query.strip() if isinstance(query, str) else ""
    if not normalized_query:
        return {
            "success": True,
            "matches": [],
            "count": 0,
            "message": "Enter a name or phone digits.",
        }
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("Search limit must be a positive integer.")
    limit = min(limit, MAX_RESULTS)

    if _is_phone_query(normalized_query):
        query_digits = _digits(normalized_query)
        if not query_digits:
            return {
                "success": True,
                "matches": [],
                "count": 0,
                "message": "Enter a name or phone digits.",
            }
        people = _all_contacts()
        selected = [
            person
            for person in people
            if any(
                query_digits in _digits(phone)
                for phone in _field_values(person.get("phoneNumbers", []))
            )
        ]
        matches = _unique_contacts(selected, limit)
    else:
        matches = _search_names(normalized_query, limit)

    return {
        "success": True,
        "matches": matches,
        "count": len(matches),
        "message": "Search complete." if matches else "No matching contacts found.",
    }


def _validate_contact(name: str, phone: str, email: str) -> tuple[str, str, str]:
    name = name.strip() if isinstance(name, str) else ""
    phone = phone.strip() if isinstance(phone, str) else ""
    email = email.strip() if isinstance(email, str) else ""

    if not name:
        raise ValueError("Contact name is required.")
    if not phone:
        raise ValueError("Contact phone number is required.")
    phone_digits = _digits(phone)
    if not 7 <= len(phone_digits) <= 15:
        raise ValueError("Enter a phone number containing 7 to 15 digits.")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid email address.")
    return name, phone, email


def _duplicate_phone(phone: str) -> dict[str, Any] | None:
    target_digits = _digits(phone)
    for person in _all_contacts():
        if any(
            _digits(existing_phone) == target_digits
            for existing_phone in _field_values(person.get("phoneNumbers", []))
        ):
            return _format_contact(person)
    return None


def save_contact(
    name: str, phone: str, email: str = "", confirmed: bool = False
) -> dict[str, Any]:
    """Preview and, after explicit confirmation, create a Google contact."""
    name, phone, email = _validate_contact(name, phone, email)
    preview = {
        "name": name,
        "phone_numbers": [phone],
        "emails": [email] if email else [],
    }
    duplicate = _duplicate_phone(phone)
    if duplicate:
        return {
            "success": False,
            "created": False,
            "requires_confirmation": False,
            "contact": duplicate,
            "message": "A contact with this phone number already exists.",
        }

    if not confirmed:
        return {
            "success": True,
            "created": False,
            "requires_confirmation": True,
            "preview": preview,
            "message": "Review this contact and confirm before it is created.",
        }

    body: dict[str, Any] = {"names": [{"givenName": name}]}
    body["phoneNumbers"] = [{"value": phone, "type": "mobile"}]
    if email:
        body["emailAddresses"] = [{"value": email}]
    service = get_contacts_service()
    created = _execute(
        service.people().createContact(body=body, personFields=CONTACT_FIELDS)
    )
    return {
        "success": True,
        "created": True,
        "requires_confirmation": False,
        "contact": _format_contact(created),
        "message": "Contact created successfully.",
    }
