"""Google Photos Picker sessions and server-side selected-media transfer."""

import mimetypes
import os
import re
import hashlib
import tempfile
from pathlib import Path
from typing import Any

from google.auth.transport.requests import AuthorizedSession

from agent.auth.gmail_auth import PHOTOS_PICKER_SCOPES, get_credentials
from agent.services.drive_service import upload_file, validate_filename


PHOTOS_API = "https://photospicker.googleapis.com/v1"
MAX_UPLOAD_BYTES = int(os.getenv("DRIVE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))


def _session() -> AuthorizedSession:
    return AuthorizedSession(get_credentials(required_scopes=PHOTOS_PICKER_SCOPES))


def create_picker_session() -> dict[str, Any]:
    response = _session().post(f"{PHOTOS_API}/sessions", json={}, timeout=20)
    response.raise_for_status()
    session = response.json()
    if not session.get("id") or not session.get("pickerUri"):
        raise RuntimeError("Google Photos Picker returned an incomplete session.")
    if not session["pickerUri"].startswith("https://photos.google.com/"):
        raise RuntimeError("Google Photos Picker returned an unexpected picker URL.")
    return {
        "id": session["id"],
        "picker_uri": session["pickerUri"],
        "poll_interval": session.get("pollingConfig", {}).get("pollInterval", "3s"),
        "expire_time": session.get("expireTime"),
    }


def get_picker_session(session_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", session_id or ""):
        raise ValueError("Invalid Photos Picker session ID.")
    response = _session().get(f"{PHOTOS_API}/sessions/{session_id}", timeout=20)
    response.raise_for_status()
    session = response.json()
    return {
        "id": session.get("id"),
        "media_items_set": bool(session.get("mediaItemsSet")),
        "expire_time": session.get("expireTime"),
        "poll_interval": session.get("pollingConfig", {}).get("pollInterval", "3s"),
    }


def list_selected_media(
    session_id: str,
    page_token: str | None = None,
    page_size: int = 50,
) -> dict[str, Any]:
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100.")
    session = get_picker_session(session_id)
    if not session["media_items_set"]:
        return {"media_items": [], "next_page_token": None, "ready": False}

    params: dict[str, Any] = {"sessionId": session_id, "pageSize": page_size}
    if page_token:
        params["pageToken"] = page_token
    response = _session().get(f"{PHOTOS_API}/mediaItems", params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    items = []
    for item in data.get("mediaItems", []):
        media_file = item.get("mediaFile", {})
        items.append(
            {
                "id": item.get("id"),
                "filename": media_file.get("filename", "Google Photos media"),
                "mime_type": media_file.get("mimeType", "application/octet-stream"),
                "create_time": item.get("createTime"),
                "width": media_file.get("mediaFileMetadata", {}).get("width"),
                "height": media_file.get("mediaFileMetadata", {}).get("height"),
                "video": item.get("type") == "VIDEO",
            }
        )
    return {
        "media_items": items,
        "next_page_token": data.get("nextPageToken"),
        "ready": True,
    }


def delete_picker_session(session_id: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", session_id or ""):
        raise ValueError("Invalid Photos Picker session ID.")
    response = _session().delete(f"{PHOTOS_API}/sessions/{session_id}", timeout=20)
    if response.status_code != 404:
        response.raise_for_status()


def save_selected_media_to_drive(
    session_id: str,
    media_item_ids: list[str],
    parent_id: str | None = None,
) -> list[dict[str, Any]]:
    if not media_item_ids:
        raise ValueError("Select at least one Google Photos item.")
    if len(media_item_ids) > 20 or len(set(media_item_ids)) != len(media_item_ids):
        raise ValueError("Select between 1 and 20 unique Photos items.")

    session = get_picker_session(session_id)
    if not session["media_items_set"]:
        raise ValueError("Google Photos selection is not complete yet.")

    available: dict[str, dict[str, Any]] = {}
    session_token = None
    while True:
        params: dict[str, Any] = {"sessionId": session_id, "pageSize": 100}
        if session_token:
            params["pageToken"] = session_token
        response = _session().get(f"{PHOTOS_API}/mediaItems", params=params, timeout=20)
        response.raise_for_status()
        page = response.json()
        for item in page.get("mediaItems", []):
            if item.get("id") in media_item_ids:
                available[item["id"]] = item
        session_token = page.get("nextPageToken")
        if not session_token:
            break

    if set(available) != set(media_item_ids):
        raise PermissionError("One or more selected media items are not in this Picker session.")

    saved = []
    for item_id in media_item_ids:
        item = available[item_id]
        media_file = item.get("mediaFile", {})
        base_url = media_file.get("baseUrl")
        mime_type = media_file.get("mimeType", "application/octet-stream")
        if not base_url or not base_url.startswith("https://"):
            raise RuntimeError("Google Photos returned an invalid media download URL.")
        filename = validate_filename(
            Path(media_file.get("filename") or f"photos-{item_id}").name
        )
        download_url = base_url + ("=dv" if item.get("type") == "VIDEO" else "=d")
        temp_path = None
        try:
            with _session().get(download_url, stream=True, timeout=60) as response:
                response.raise_for_status()
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_UPLOAD_BYTES:
                    raise ValueError(f"{filename} exceeds the configured upload size limit.")
                total = 0
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=Path(filename).suffix
                ) as temp:
                    temp_path = temp.name
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > MAX_UPLOAD_BYTES:
                            raise ValueError(
                                f"{filename} exceeds the configured upload size limit."
                            )
                        temp.write(chunk)
            saved.append(
                upload_file(
                    temp_path,
                    filename=filename,
                    mime_type=mime_type
                    or mimetypes.guess_type(filename)[0]
                    or "application/octet-stream",
                    parent_id=parent_id,
                    operation_id=hashlib.sha256(
                        f"{session_id}:{item_id}".encode("utf-8")
                    ).hexdigest(),
                )
            )
        finally:
            if temp_path:
                os.unlink(temp_path)
    return saved
