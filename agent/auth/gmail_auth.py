"""
auth/gmail_auth.py
------------------
Handles shared Google OAuth 2.0 authentication for Gmail and Contacts.

Responsibilities:
  - Define Gmail and Contacts OAuth scopes.
  - Load existing token.json when valid.
  - Automatically refresh expired access tokens using the refresh token.
  - Run the browser-based OAuth flow for first-time setup or reauthorization.
  - Preserve Gmail-only use while clearly requiring reauthorization for
    expanded Contacts scopes.
  - Never log, expose, or print client secrets or tokens.
"""

from pathlib import Path
from collections.abc import Sequence

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


# ── Directory and File Locations ──────────────────────────────────────────────
# __file__ is auth/gmail_auth.py -> .parents[1] is the agent/ root folder.
AGENT_DIR = Path(__file__).resolve().parents[1]

CREDENTIALS_FILE = AGENT_DIR / "credentials.json"
TOKEN_FILE = AGENT_DIR / "token.json"

# Minimum OAuth scope needed for full email assistant capabilities:
# - Reading and searching messages
# - Creating drafts
# - Sending emails and replies
# - Adding/removing labels (mark read/unread, archive)
# - Moving messages to trash
# Note: gmail.modify does NOT grant permanent account-level deletion.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

CONTACTS_SCOPES = [
    "https://www.googleapis.com/auth/contacts.readonly",
    "https://www.googleapis.com/auth/contacts",
]

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
]

TASKS_SCOPES = [
    "https://www.googleapis.com/auth/tasks",
]

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

PHOTOS_PICKER_SCOPES = [
    "https://www.googleapis.com/auth/photospicker.mediaitems.readonly",
]

ALL_SCOPES = [
    *GMAIL_SCOPES,
    *CONTACTS_SCOPES,
    *CALENDAR_SCOPES,
    *TASKS_SCOPES,
    *DRIVE_SCOPES,
    *PHOTOS_PICKER_SCOPES,
]


def check_scope_coverage(
    credentials: Credentials, required_scopes: Sequence[str] = GMAIL_SCOPES
) -> bool:
    """
    Check if the current credentials contain all requested OAuth scopes.

    Returns:
        True if all required scopes are covered, False otherwise.
    """
    if not credentials or not credentials.scopes:
        return False
    return set(required_scopes).issubset(set(credentials.scopes))


def get_credentials(
    force_reauth: bool = False,
    required_scopes: Sequence[str] = GMAIL_SCOPES,
) -> Credentials:
    """
    Return valid Google OAuth credentials with the requested scopes.

    Workflow:
      1. Load the existing token without overriding its recorded scope set.
      2. Refresh an expired token when possible.
      3. Raise an actionable error for missing scopes or failed refreshes.
      4. Run the browser flow only when no token exists or reauthorization is
         explicitly requested.

    Args:
        force_reauth: Set to True to force the browser OAuth flow even if token.json exists.
        required_scopes: Scopes the requested API operation needs.

    Returns:
        An authorized Credentials object.

    Raises:
        FileNotFoundError: If credentials.json is missing.
        RuntimeError: If authentication fails.
    """
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Cannot find credentials.json at: {CREDENTIALS_FILE}\n"
            "Download your OAuth 2.0 'Desktop app' client JSON from Google Cloud Console\n"
            "and place it inside the agent/ folder as 'credentials.json'."
        )

    credentials = None

    # Step 1: Load existing token if available and reauth is not forced.
    if TOKEN_FILE.exists() and not force_reauth:
        try:
            credentials = Credentials.from_authorized_user_file(
                str(TOKEN_FILE)
            )
        except (OSError, ValueError, KeyError) as token_error:
            raise RuntimeError(
                "The saved Google OAuth token could not be read. "
                "Reauthorize with: python -m agent.auth.gmail_auth"
            ) from token_error

    # Step 2: Auto-refresh if the access token has expired.
    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            # Save the refreshed token immediately.
            TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
        except Exception as refresh_error:
            raise RuntimeError(
                "Google OAuth token refresh failed. Reauthorize with: "
                "python -m agent.auth.gmail_auth"
            ) from refresh_error

    # Do not turn an API/tool call into an unexpected browser authorization.
    if credentials and not credentials.valid:
        raise RuntimeError(
            "Google OAuth credentials are expired or invalid. Reauthorize with: "
            "python -m agent.auth.gmail_auth"
        )

    if credentials:
        missing_scopes = set(required_scopes) - set(credentials.scopes or [])
        if missing_scopes:
            missing = ", ".join(sorted(missing_scopes))
            raise RuntimeError(
                "Google OAuth token is missing required scopes: "
                f"{missing}. Reauthorize with: python -m agent.auth.gmail_auth"
            )

    # Step 3: Run an interactive flow only for first-time setup or explicit
    # reauthorization. Requesting the combined scope set preserves Gmail access.
    if not credentials or force_reauth:
        print("\nOpening browser for Google account authorization...")
        print(f"Requesting permissions: {', '.join(ALL_SCOPES)}\n")

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE),
            scopes=ALL_SCOPES,
        )
        try:
            credentials = flow.run_local_server(
                host="localhost",
                port=0,
                open_browser=True,
            )
        except Exception as auth_error:
            raise RuntimeError(
                "Google OAuth authorization failed. Check the Desktop app "
                "credentials and try again."
            ) from auth_error

        # Step 4: Save new authorization for subsequent runs.
        TOKEN_FILE.write_text(credentials.to_json(), encoding="utf-8")
        print("Authorization successful! Token saved to token.json.")

    missing_scopes = set(required_scopes) - set(credentials.scopes or [])
    if missing_scopes:
        raise RuntimeError(
            "Google OAuth authorization did not grant all requested scopes. "
            "Reauthorize with: python -m agent.auth.gmail_auth"
        )

    return credentials


# ── Run directly to reauthorize with expanded scopes ─────────────────────────
# Usage: python -m agent.auth.gmail_auth
if __name__ == "__main__":
    print("=" * 60)
    print("Google Gmail and Contacts Authorization Flow")
    print("=" * 60)
    print("This will request access for Gmail and Google Contacts:")
    for scope in ALL_SCOPES:
        print(f"  - {scope}")
    print("\nStarting browser authorization...")

    try:
        # Force reauthorization to ensure the new scopes are granted and saved
        creds = get_credentials(force_reauth=True)
        print("\nSUCCESS: Gmail authorization completed!")
        print(f"Token file: {TOKEN_FILE}")
    except Exception as err:
        print(f"\nERROR: Authorization failed: {err}")
