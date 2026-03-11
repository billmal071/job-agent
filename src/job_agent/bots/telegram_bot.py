"""Telegram bot with long-polling for interactive job management."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from job_agent.bots.commands import BotCommandHandler
from job_agent.config import Settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class TelegramBot:
    """Interactive Telegram bot using getUpdates long-polling."""

    def __init__(self, settings: Settings):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.handler = BotCommandHandler(settings)
        self._base_url = f"https://api.telegram.org/bot{self.token}"

    def start(self) -> None:
        """Run the polling loop (blocking)."""
        if not self.token or not self.chat_id:
            raise RuntimeError(
                "Telegram bot requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"
            )

        log.info("telegram_bot_starting", chat_id=self.chat_id)
        offset = 0
        while True:
            try:
                updates = self._poll(offset)
                for update in updates:
                    offset = update["update_id"] + 1
                    self._handle_update(update)
            except KeyboardInterrupt:
                log.info("telegram_bot_stopped")
                break
            except Exception as e:
                log.error("telegram_poll_error", error=str(e))
                time.sleep(5)

    def _poll(self, offset: int) -> list[dict]:
        """Long-poll for updates from Telegram."""
        url = f"{self._base_url}/getUpdates?offset={offset}&timeout=30"
        req = urllib.request.Request(url, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                data = json.loads(resp.read())
                if data.get("ok"):
                    return data.get("result", [])
                return []
        except urllib.error.URLError:
            return []

    def _handle_update(self, update: dict) -> None:
        """Process a single update from Telegram."""
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = message.get("text", "")

        if not text or not chat_id:
            return

        # Security: only respond to the configured chat
        if chat_id != self.chat_id:
            log.warning("telegram_unauthorized", chat_id=chat_id)
            return

        response = self.handler.route_command(text)
        self._send_reply(chat_id, response)

    def _send_reply(self, chat_id: str, text: str) -> bool:
        """Send a text message reply."""
        url = f"{self._base_url}/sendMessage"
        payload = json.dumps(
            {
                "chat_id": chat_id,
                "text": text,
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
                return resp.status == 200
        except urllib.error.URLError as e:
            log.error("telegram_send_failed", error=str(e))
            return False
