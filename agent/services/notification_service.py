"""
services/notification_service.py
--------------------------------
Notification delivery interface and adapters.

Supports:
  - Telegram bot messaging (via Bot API).
  - Console / local fallback delivery.
"""

import os
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx


class NotificationDeliveryAdapter(ABC):
    """Abstract base class for notification delivery channels."""

    @abstractmethod
    def deliver(self, text: str, recipient_id: str | None = None) -> dict[str, Any]:
        """
        Deliver a notification message.

        Returns:
            Dict containing:
              - 'success': bool
              - 'channel': str
              - 'delivery_id': optional str
              - 'error': optional error message
        """
        pass


class TelegramDeliveryAdapter(NotificationDeliveryAdapter):
    """
    Delivers notifications via Telegram Bot API.
    Reads credentials from TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.
    """

    def __init__(
        self,
        bot_token: str | None = None,
        default_chat_id: str | None = None,
        max_retries: int = 3,
        timeout: float = 10.0,
    ):
        self.bot_token = (bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")).strip()
        self.default_chat_id = (
            default_chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        ).strip()
        self.max_retries = max_retries
        self.timeout = timeout

    def deliver(self, text: str, recipient_id: str | None = None) -> dict[str, Any]:
        chat_id = (recipient_id or self.default_chat_id).strip()

        if not self.bot_token:
            return {
                "success": False,
                "channel": "telegram",
                "error": (
                    "Telegram bot token is not configured. "
                    "Set TELEGRAM_BOT_TOKEN in your agent/.env file."
                ),
            }

        if not chat_id:
            return {
                "success": False,
                "channel": "telegram",
                "error": (
                    "Telegram recipient chat ID is not configured. "
                    "Set TELEGRAM_CHAT_ID in your agent/.env file or specify a recipient_id."
                ),
            }

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                response = httpx.post(url, json=payload, timeout=self.timeout)
                if response.status_code == 200:
                    data = response.json()
                    msg_id = data.get("result", {}).get("message_id")
                    return {
                        "success": True,
                        "channel": "telegram",
                        "delivery_id": str(msg_id) if msg_id else "ok",
                        "chat_id": chat_id,
                    }
                else:
                    last_error = f"HTTP {response.status_code}"
            except Exception as exc:
                last_error = type(exc).__name__

            # Exponential backoff between retries (e.g., 0.5s, 1.0s)
            if attempt < self.max_retries:
                time.sleep(0.5 * attempt)

        return {
            "success": False,
            "channel": "telegram",
            "error": f"Failed after {self.max_retries} attempts: {last_error}",
        }


class ConsoleDeliveryAdapter(NotificationDeliveryAdapter):
    """Local console delivery adapter for development and testing."""

    def deliver(self, text: str, recipient_id: str | None = None) -> dict[str, Any]:
        recipient = recipient_id or "console"
        formatted_alert = f"\n[🔔 SCHEDULED REMINDER ALERT -> {recipient}]\n{text}\n"
        print(formatted_alert)
        return {
            "success": True,
            "channel": "console",
            "delivery_id": f"console-{int(time.time())}",
        }


def get_delivery_adapter(channel: str = "telegram") -> NotificationDeliveryAdapter:
    """Factory to get the configured notification delivery adapter."""
    ch = (channel or "").strip().lower()
    if ch == "console":
        return ConsoleDeliveryAdapter()
    if ch == "telegram":
        return TelegramDeliveryAdapter()
    raise ValueError("Unsupported notification channel. Use 'telegram' or 'console'.")
