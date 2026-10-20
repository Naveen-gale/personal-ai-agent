"""Mocked tests for Google Photos Picker session lifecycle."""

from unittest.mock import MagicMock, patch

from agent.services import photos_picker_service


def test_create_picker_session_returns_only_session_launch_data():
    response = MagicMock()
    response.json.return_value = {
        "id": "session-123",
        "pickerUri": "https://photos.google.com/picker/session-123",
        "pollingConfig": {"pollInterval": "4s"},
        "expireTime": "2026-10-20T10:00:00Z",
    }
    session = MagicMock()
    session.post.return_value = response

    with patch.object(photos_picker_service, "_session", return_value=session):
        result = photos_picker_service.create_picker_session()

    assert result["id"] == "session-123"
    assert result["picker_uri"].startswith("https://photos.google.com/")
    assert result["poll_interval"] == "4s"
    assert "access_token" not in result
    session.post.assert_called_once()


def test_list_selected_media_hides_temporary_download_urls():
    session = MagicMock()
    session.get.side_effect = [
        MagicMock(
            json=MagicMock(
                return_value={
                    "id": "session-123",
                    "mediaItemsSet": True,
                    "expireTime": "2026-10-20T10:00:00Z",
                    "pollingConfig": {"pollInterval": "3s"},
                }
            )
        ),
        MagicMock(
            json=MagicMock(
                return_value={
                    "mediaItems": [
                        {
                            "id": "photo-1",
                            "type": "PHOTO",
                            "createTime": "2026-10-20T08:00:00Z",
                            "mediaFile": {
                                "filename": "photo.jpg",
                                "mimeType": "image/jpeg",
                                "baseUrl": "https://private.example/temp",
                            },
                        }
                    ]
                }
            )
        ),
    ]
    with patch.object(photos_picker_service, "_session", return_value=session):
        result = photos_picker_service.list_selected_media("session-123")

    assert result["media_items"][0]["filename"] == "photo.jpg"
    assert "baseUrl" not in result["media_items"][0]
    assert result["ready"] is True

