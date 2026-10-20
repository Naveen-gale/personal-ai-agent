"""Mocked tests for Google Drive browser, content, upload, and management APIs."""

from unittest.mock import MagicMock, patch

import pytest

from agent.services import drive_service


def test_drive_scopes_use_the_existing_shared_authorization():
    from agent.auth.gmail_auth import DRIVE_SCOPES, PHOTOS_PICKER_SCOPES, ALL_SCOPES

    assert DRIVE_SCOPES == ["https://www.googleapis.com/auth/drive"]
    assert PHOTOS_PICKER_SCOPES == [
        "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
    ]
    assert set(DRIVE_SCOPES + PHOTOS_PICKER_SCOPES).issubset(set(ALL_SCOPES))


def test_list_drive_files_filters_and_paginates():
    service = MagicMock()
    service.files.return_value.get.return_value.execute.return_value = {
        "id": "folder-1",
        "mimeType": drive_service.FOLDER_MIME_TYPE,
        "capabilities": {"canAddChildren": True},
    }
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "f-1", "name": "Plan.pdf"}],
        "nextPageToken": "next",
    }

    with patch.object(drive_service, "get_drive_service", return_value=service):
        result = drive_service.list_drive_files(
            parent_id="folder-1",
            name_query="O'Reilly",
            mime_type="application/pdf",
            page_token="page-1",
            page_size=25,
        )

    assert result["files"][0]["id"] == "f-1"
    assert result["next_page_token"] == "next"
    request = service.files.return_value.list.call_args.kwargs
    assert "'folder-1' in parents" in request["q"]
    assert "name contains 'O\\'Reilly'" in request["q"]
    assert "mimeType = 'application/pdf'" in request["q"]
    assert request["pageToken"] == "page-1"


def test_resolve_folder_path_refuses_duplicate_names():
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {"id": "folder-a", "name": "Projects"},
            {"id": "folder-b", "name": "Projects"},
        ]
    }
    with patch.object(drive_service, "get_drive_service", return_value=service):
        with pytest.raises(ValueError, match="ambiguous"):
            drive_service.resolve_folder_path("Projects")


def test_upload_uses_resumable_media_and_returns_confirmed_file(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello", encoding="utf-8")
    service = MagicMock()
    create_request = service.files.return_value.create.return_value
    service.files.return_value.list.return_value.execute.return_value = {"files": []}
    create_request.next_chunk.side_effect = [
        (None, None),
        (None, {"id": "drive-file", "name": "notes.txt", "mimeType": "text/plain"}),
    ]

    with patch.object(drive_service, "get_drive_service", return_value=service):
        result = drive_service.upload_file(
            file_path,
            "notes.txt",
            "text/plain",
            operation_id="upload-operation-1",
        )

    assert result["id"] == "drive-file"
    assert result["webViewLink"] == "https://drive.google.com/open?id=drive-file"
    create_args = service.files.return_value.create.call_args.kwargs
    assert create_args["body"]["appProperties"]["personalAiAgentOperationId"] == "upload-operation-1"
    assert create_args["media_body"].resumable() is True
    assert create_request.next_chunk.call_count == 2


def test_upload_retry_with_existing_operation_id_does_not_duplicate(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("hello", encoding="utf-8")
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [{"id": "already-uploaded", "name": "notes.txt"}]
    }

    with patch.object(drive_service, "get_drive_service", return_value=service):
        result = drive_service.upload_file(
            file_path,
            "notes.txt",
            "text/plain",
            operation_id="upload-operation-1",
        )

    assert result["id"] == "already-uploaded"
    service.files.return_value.create.assert_not_called()


def test_delete_moves_to_trash_instead_of_permanent_delete():
    service = MagicMock()
    service.files.return_value.get.return_value.execute.return_value = {
        "id": "file-1",
        "name": "Report.pdf",
        "mimeType": "application/pdf",
        "parents": ["root"],
        "capabilities": {"canRead": True, "canEdit": True},
    }
    service.files.return_value.update.return_value.execute.return_value = {
        "id": "file-1",
        "name": "Report.pdf",
        "trashed": True,
    }

    with patch.object(drive_service, "get_drive_service", return_value=service):
        result = drive_service.delete_drive_item("file-1")

    assert result["trashed"] is True
    service.files.return_value.update.assert_called_once()
    assert service.files.return_value.update.call_args.kwargs["body"] == {"trashed": True}
    service.files.return_value.delete.assert_not_called()


@pytest.mark.parametrize("filename", ["", ".", "..", "../report.pdf", "C:\\report.pdf"])
def test_filename_validation_rejects_paths(filename):
    with pytest.raises(ValueError):
        drive_service.validate_filename(filename)
