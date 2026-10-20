"""Google Drive browsing, file content, uploads, and folder management."""

import io
import os
import re
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from agent.auth.gmail_auth import DRIVE_SCOPES, get_credentials


FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME_TYPE = "application/vnd.google-apps.document"
GOOGLE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDE_MIME_TYPE = "application/vnd.google-apps.presentation"
MAX_PAGE_SIZE = 100
MAX_CONTENT_BYTES = int(os.getenv("DRIVE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_EXTRACTED_TEXT_CHARS = 100_000


def get_drive_service():
    """Create an authorized Drive API client from the shared OAuth token."""
    credentials = get_credentials(required_scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _escape_query_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _file_link(file_id: str, metadata: dict[str, Any]) -> str:
    return metadata.get("webViewLink") or f"https://drive.google.com/open?id={file_id}"


def _get_metadata(service, file_id: str) -> dict[str, Any]:
    metadata = (
        service.files()
        .get(
            fileId=file_id,
            fields="id,name,mimeType,size,modifiedTime,webViewLink,thumbnailLink,parents,capabilities",
            supportsAllDrives=True,
        )
        .execute()
    )
    if metadata.get("capabilities", {}).get("canRead") is False:
        raise PermissionError("The authenticated Google account cannot read this Drive file.")
    return metadata


def list_drive_files(
    parent_id: str | None = None,
    name_query: str | None = None,
    mime_type: str | None = None,
    page_token: str | None = None,
    page_size: int = 50,
    all_files: bool = False,
    order_by: str = "folder,name",
) -> dict[str, Any]:
    """List files in a folder or Drive root, with optional filters and pagination."""
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}.")
    if order_by not in {"folder,name", "modifiedTime desc", "name"}:
        raise ValueError("Unsupported Drive sort order.")

    service = get_drive_service()
    query_parts = ["trashed = false"]
    if parent_id:
        _ensure_folder(service, parent_id)
        query_parts.append(f"'{_escape_query_value(parent_id)}' in parents")
    elif not all_files:
        query_parts.append("'root' in parents")
    if name_query:
        query_parts.append(f"name contains '{_escape_query_value(name_query)}'")
    if mime_type:
        operator = "contains" if mime_type.endswith("/") else "="
        query_parts.append(f"mimeType {operator} '{_escape_query_value(mime_type)}'")

    result = (
        service.files()
        .list(
            q=" and ".join(query_parts),
            pageSize=page_size,
            pageToken=page_token,
            orderBy=order_by,
            fields=(
                "nextPageToken,files(id,name,mimeType,size,modifiedTime,"
                "webViewLink,thumbnailLink,parents)"
            ),
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    return {
        "files": result.get("files", []),
        "next_page_token": result.get("nextPageToken"),
    }


def download_drive_file(file_id: str) -> dict[str, Any]:
    """Download a supported Drive binary or Workspace export with a bounded size."""
    service = get_drive_service()
    metadata = _get_metadata(service, file_id)
    source_mime = metadata.get("mimeType", "application/octet-stream")
    if metadata.get("size") and int(metadata["size"]) > MAX_CONTENT_BYTES:
        raise ValueError(f"File exceeds the {MAX_CONTENT_BYTES}-byte download limit.")

    filename = metadata["name"]
    if source_mime == GOOGLE_DOC_MIME_TYPE:
        export_mime = "application/pdf"
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
    elif source_mime == GOOGLE_SHEET_MIME_TYPE:
        export_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        if not filename.lower().endswith(".xlsx"):
            filename += ".xlsx"
    elif source_mime == GOOGLE_SLIDE_MIME_TYPE:
        export_mime = "application/pdf"
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
    else:
        export_mime = source_mime
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=3)
        if buffer.tell() > MAX_CONTENT_BYTES:
            raise ValueError(f"Downloaded content exceeds the {MAX_CONTENT_BYTES}-byte limit.")
    return {
        "filename": validate_filename(filename),
        "mime_type": export_mime,
        "content": buffer.getvalue(),
    }


def get_drive_file_content(file_id: str) -> dict[str, Any]:
    """Read supported text, PDF, and Google Workspace document content."""
    service = get_drive_service()
    metadata = _get_metadata(service, file_id)
    mime_type = metadata.get("mimeType", "application/octet-stream")
    if metadata.get("size") and int(metadata["size"]) > MAX_CONTENT_BYTES:
        raise ValueError(
            f"File exceeds the {MAX_CONTENT_BYTES}-byte content extraction limit."
        )

    if mime_type == GOOGLE_DOC_MIME_TYPE:
        request = service.files().export_media(fileId=file_id, mimeType="text/plain")
        content_type = "text/plain"
    elif mime_type == GOOGLE_SHEET_MIME_TYPE:
        request = service.files().export_media(fileId=file_id, mimeType="text/csv")
        content_type = "text/csv"
    elif mime_type == GOOGLE_SLIDE_MIME_TYPE:
        request = service.files().export_media(fileId=file_id, mimeType="application/pdf")
        content_type = "application/pdf"
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        content_type = mime_type

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=3)
        if buffer.tell() > MAX_CONTENT_BYTES:
            raise ValueError(
                f"Downloaded content exceeds the {MAX_CONTENT_BYTES}-byte extraction limit."
            )
    raw = buffer.getvalue()

    if content_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(raw))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    elif content_type.startswith("text/") or content_type in {
        "application/json",
        "application/rtf",
        "text/csv",
    }:
        text = raw.decode("utf-8", errors="replace")
    else:
        raise ValueError(
            f"Content extraction is not supported for {content_type}. "
            "Download the file or export it to a supported text format."
        )

    truncated = len(text) > MAX_EXTRACTED_TEXT_CHARS
    if truncated:
        text = text[:MAX_EXTRACTED_TEXT_CHARS]
    return {
        "id": file_id,
        "name": metadata["name"],
        "mime_type": mime_type,
        "size": metadata.get("size"),
        "web_view_link": _file_link(file_id, metadata),
        "text": text,
        "truncated": truncated,
    }


def _ensure_folder(service, folder_id: str) -> dict[str, Any]:
    if folder_id == "root":
        return {"id": "root", "name": "My Drive", "mimeType": FOLDER_MIME_TYPE}
    folder = _get_metadata(service, folder_id)
    if folder.get("mimeType") != FOLDER_MIME_TYPE:
        raise ValueError("The destination ID does not identify a Drive folder.")
    if folder.get("capabilities", {}).get("canAddChildren") is False:
        raise PermissionError("The authenticated Google account cannot add files to this folder.")
    return folder


def create_folder(name: str, parent_id: str | None = None) -> dict[str, Any]:
    """Create a Drive folder, rejecting path-like or invalid names."""
    name = validate_filename(name)
    service = get_drive_service()
    body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME_TYPE}
    if parent_id:
        _ensure_folder(service, parent_id)
        body["parents"] = [parent_id]
    parent_query = (
        f"'{_escape_query_value(parent_id)}' in parents"
        if parent_id
        else "'root' in parents"
    )
    duplicates = (
        service.files()
        .list(
            q=(
                "trashed = false and "
                f"mimeType = '{FOLDER_MIME_TYPE}' and "
                f"name = '{_escape_query_value(name)}' and {parent_query}"
            ),
            pageSize=2,
            fields="files(id,name)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
        .get("files", [])
    )
    if duplicates:
        raise ValueError(
            f"A folder named '{name}' already exists in that location. "
            "Choose it or provide a different name."
        )
    created = service.files().create(
        body=body,
        fields="id,name,mimeType,parents,webViewLink",
        supportsAllDrives=True,
    ).execute()
    created["webViewLink"] = _file_link(created["id"], created)
    return created


def resolve_folder_path(path: str, create_missing: bool = False) -> dict[str, Any]:
    """Resolve a slash-separated folder path, refusing ambiguous duplicates."""
    parts = [part.strip() for part in path.replace("\\", "/").split("/") if part.strip()]
    if not parts:
        raise ValueError("A non-empty Drive folder path is required.")
    service = get_drive_service()
    parent_id: str | None = None
    current: dict[str, Any] | None = None

    for part in parts:
        query = [
            f"mimeType = '{FOLDER_MIME_TYPE}'",
            "trashed = false",
            f"name = '{_escape_query_value(validate_filename(part))}'",
        ]
        query.append(
            f"'{_escape_query_value(parent_id)}' in parents"
            if parent_id
            else "'root' in parents"
        )
        matches = (
            service.files()
            .list(
                q=" and ".join(query),
                pageSize=100,
                fields="files(id,name,mimeType,parents,webViewLink)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
            .get("files", [])
        )
        if len(matches) > 1:
            raise ValueError(f"Folder path is ambiguous: multiple folders named '{part}'.")
        if not matches:
            if not create_missing:
                raise FileNotFoundError(f"Drive folder '{part}' was not found.")
            current = create_folder(part, parent_id)
        else:
            current = matches[0]
        parent_id = current["id"]

    return current or {"id": "root", "name": "My Drive", "mimeType": FOLDER_MIME_TYPE}


def validate_filename(filename: str) -> str:
    """Validate a single filename or folder name without path separators."""
    if not isinstance(filename, str):
        raise ValueError("A filename is required.")
    name = filename.strip()
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or len(name) > 255
        or any(ord(character) < 32 for character in name)
    ):
        raise ValueError("Filename must be a single non-empty name of at most 255 characters.")
    return name


def upload_file(
    file_path: str | Path,
    filename: str,
    mime_type: str,
    parent_id: str | None = None,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Resumably upload a file, returning metadata only after Drive confirms creation."""
    filename = validate_filename(filename)
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}/"
        r"[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]{0,126}",
        mime_type or "",
    ):
        raise ValueError("A valid MIME type is required.")
    service = get_drive_service()
    if parent_id:
        _ensure_folder(service, parent_id)

    body: dict[str, Any] = {"name": filename}
    if parent_id:
        body["parents"] = [parent_id]

    if operation_id:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", operation_id):
            raise ValueError("Invalid upload operation ID.")
        body["appProperties"] = {"personalAiAgentOperationId": operation_id}
        existing = (
            service.files()
            .list(
                q=(
                    "appProperties has { key='personalAiAgentOperationId' and "
                    f"value='{_escape_query_value(operation_id)}' }}"
                ),
                pageSize=2,
                fields="files(id,name,mimeType,parents,webViewLink)",
                supportsAllDrives=True,
            )
            .execute()
            .get("files", [])
        )
        if existing:
            if len(existing) > 1:
                raise RuntimeError("Upload operation ID matched multiple Drive files.")
            return existing[0]

    media = MediaFileUpload(
        str(file_path),
        mimetype=mime_type,
        chunksize=5 * 1024 * 1024,
        resumable=True,
    )
    request = service.files().create(
        body=body,
        media_body=media,
        fields="id,name,mimeType,size,parents,webViewLink",
        supportsAllDrives=True,
    )
    result = None
    while result is None:
        _, result = request.next_chunk(num_retries=3)
    if not result.get("id"):
        raise RuntimeError("Google Drive did not confirm file creation.")
    result["webViewLink"] = _file_link(result["id"], result)
    return result


def _get_mutable_file(service, file_id: str) -> dict[str, Any]:
    metadata = _get_metadata(service, file_id)
    capabilities = metadata.get("capabilities", {})
    if capabilities.get("canEdit") is False:
        raise PermissionError("The authenticated Google account cannot edit this Drive item.")
    return metadata


def rename_drive_item(file_id: str, name: str) -> dict[str, Any]:
    name = validate_filename(name)
    service = get_drive_service()
    _get_mutable_file(service, file_id)
    result = service.files().update(
        fileId=file_id,
        body={"name": name},
        fields="id,name,mimeType,parents,webViewLink",
        supportsAllDrives=True,
    ).execute()
    result["webViewLink"] = _file_link(file_id, result)
    return result


def move_drive_item(file_id: str, destination_folder_id: str) -> dict[str, Any]:
    service = get_drive_service()
    item = _get_mutable_file(service, file_id)
    _ensure_folder(service, destination_folder_id)
    if item.get("mimeType") == FOLDER_MIME_TYPE:
        ancestor_id = destination_folder_id
        inspected = set()
        while ancestor_id != "root" and ancestor_id and ancestor_id not in inspected:
            if ancestor_id == file_id:
                raise ValueError("A Drive folder cannot be moved into itself or one of its descendants.")
            inspected.add(ancestor_id)
            ancestor = _get_metadata(service, ancestor_id)
            parents = ancestor.get("parents", [])
            ancestor_id = parents[0] if parents else "root"
    old_parents = ",".join(item.get("parents", []))
    if destination_folder_id in item.get("parents", []):
        return item
    result = service.files().update(
        fileId=file_id,
        addParents=destination_folder_id,
        removeParents=old_parents,
        fields="id,name,mimeType,parents,webViewLink",
        supportsAllDrives=True,
    ).execute()
    result["webViewLink"] = _file_link(file_id, result)
    return result


def copy_drive_file(file_id: str, name: str | None = None, parent_id: str | None = None):
    service = get_drive_service()
    metadata = _get_metadata(service, file_id)
    if metadata.get("mimeType") == FOLDER_MIME_TYPE:
        raise ValueError("Google Drive does not support copying folders through this operation.")
    body: dict[str, Any] = {}
    if name:
        body["name"] = validate_filename(name)
    if parent_id:
        _ensure_folder(service, parent_id)
        body["parents"] = [parent_id]
    result = service.files().copy(
        fileId=file_id,
        body=body,
        fields="id,name,mimeType,parents,webViewLink",
        supportsAllDrives=True,
    ).execute()
    result["webViewLink"] = _file_link(result["id"], result)
    return result


def delete_drive_item(file_id: str) -> dict[str, Any]:
    service = get_drive_service()
    metadata = _get_mutable_file(service, file_id)
    service.files().update(
        fileId=file_id,
        body={"trashed": True},
        fields="id,name,trashed",
        supportsAllDrives=True,
    ).execute()
    return {"id": file_id, "name": metadata["name"], "trashed": True}
