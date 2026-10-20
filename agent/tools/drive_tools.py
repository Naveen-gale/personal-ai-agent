"""Google Drive tools exposed to the personal AI agent."""

from langchain_core.tools import tool

from agent.services import drive_service
from agent.tools.confirmation import consume_tool_authorization


@tool
def list_drive_files(
    folder_id: str = "",
    name_query: str = "",
    mime_type: str = "",
    page_token: str = "",
) -> dict:
    """List Google Drive files and folders, optionally within a folder or by name/type."""
    result = drive_service.list_drive_files(
        parent_id=folder_id or None,
        name_query=name_query or None,
        mime_type=mime_type or None,
        page_token=page_token or None,
    )
    return {"success": True, **result}


@tool
def search_drive_files(query: str, mime_type: str = "") -> dict:
    """Search Google Drive by filename across the account, optionally filtering by MIME type."""
    result = drive_service.list_drive_files(
        name_query=query,
        mime_type=mime_type or None,
        all_files=True,
        order_by="modifiedTime desc",
    )
    return {"success": True, **result}


@tool
def read_drive_file(file_id: str) -> dict:
    """Read extractable text from a Google Drive PDF, text file, Doc, Sheet, or Slide."""
    content = drive_service.get_drive_file_content(file_id)
    return {"success": True, **content}


@tool
def create_drive_folder(name: str, parent_id: str = "") -> dict:
    """Create a Google Drive folder, optionally inside an existing folder ID."""
    folder = drive_service.create_folder(name, parent_id or None)
    return {"success": True, "folder": folder}


@tool
def create_drive_folder_path(path: str) -> dict:
    """Create missing folders in an explicit slash-separated Drive path."""
    folder = drive_service.resolve_folder_path(path, create_missing=True)
    return {"success": True, "folder": folder}


@tool
def rename_drive_item(file_id: str, new_name: str, confirmed: bool = False) -> dict:
    """Rename a Drive file or folder after the user confirms the exact change."""
    confirmed = confirmed and consume_tool_authorization("rename_drive_item")
    if not confirmed:
        return {
            "success": False,
            "requires_confirmation": True,
            "message": f"Please confirm renaming Drive item {file_id} to '{new_name}'.",
        }
    item = drive_service.rename_drive_item(file_id, new_name)
    return {"success": True, "item": item}


@tool
def move_drive_item(
    file_id: str,
    destination_folder_id: str,
    confirmed: bool = False,
) -> dict:
    """Move a Drive file or folder after the user confirms the destination."""
    confirmed = confirmed and consume_tool_authorization("move_drive_item")
    if not confirmed:
        return {
            "success": False,
            "requires_confirmation": True,
            "message": (
                f"Please confirm moving Drive item {file_id} "
                f"to folder {destination_folder_id}."
            ),
        }
    item = drive_service.move_drive_item(file_id, destination_folder_id)
    return {"success": True, "item": item}


@tool
def copy_drive_file(file_id: str, new_name: str = "", destination_folder_id: str = "") -> dict:
    """Copy a Google Drive file, optionally renaming it or choosing a destination folder."""
    item = drive_service.copy_drive_file(
        file_id,
        name=new_name or None,
        parent_id=destination_folder_id or None,
    )
    return {"success": True, "item": item}


@tool
def delete_drive_item(file_id: str, confirmed: bool = False) -> dict:
    """Move a Drive file or folder to trash after the user explicitly confirms."""
    confirmed = confirmed and consume_tool_authorization("delete_drive_item")
    if not confirmed:
        return {
            "success": False,
            "requires_confirmation": True,
            "message": f"Please confirm moving Drive item {file_id} to Google Drive trash.",
        }
    item = drive_service.delete_drive_item(file_id)
    return {"success": True, "item": item}


DRIVE_TOOLS = [
    list_drive_files,
    search_drive_files,
    read_drive_file,
    create_drive_folder,
    create_drive_folder_path,
    rename_drive_item,
    move_drive_item,
    copy_drive_file,
    delete_drive_item,
]
