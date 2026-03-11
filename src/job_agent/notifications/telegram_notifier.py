"""Telegram Bot API notification sender."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from job_agent.config import Settings
from job_agent.notifications.base import Notifier
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class TelegramNotifier(Notifier):
    """Send notifications via Telegram Bot API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.triggers = settings.notifications.telegram.triggers
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    def send(self, title: str, message: str, event_type: str = "") -> bool:
        if not self.should_notify(event_type, self.triggers):
            return False

        if not self.token or not self.chat_id:
            log.warning("telegram_not_configured")
            return False

        text = f"<b>{title}</b>\n{message}"
        return self._send_message(text)

    def _send_message(self, text: str) -> bool:
        """Send a message via Telegram Bot API."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
        ).encode()

        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    log.info("telegram_sent", chat_id=self.chat_id)
                    return True
                log.error("telegram_failed", status=resp.status)
                return False
        except urllib.error.URLError as e:
            log.error("telegram_failed", error=str(e))
            return False
