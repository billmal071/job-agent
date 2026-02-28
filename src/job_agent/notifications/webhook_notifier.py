"""Webhook notification sender for Slack/Discord."""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

from job_agent.config import Settings
from job_agent.notifications.base import Notifier
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class WebhookNotifier(Notifier):
    """Send notifications via webhooks (Slack/Discord)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.triggers = settings.notifications.webhook.triggers

    def send(self, title: str, message: str, event_type: str = "") -> bool:
        if not self.should_notify(event_type, self.triggers):
            return False

        success = True

        if self.settings.slack_webhook_url:
            success = self._send_slack(title, message) and success

        if self.settings.discord_webhook_url:
            success = self._send_discord(title, message) and success

        return success

    def _send_slack(self, title: str, message: str) -> bool:
        """Send a Slack webhook notification."""
        try:
            payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"Job Agent: {title}"},
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": message},
                    },
                ]
            }
            self._post_json(self.settings.slack_webhook_url, payload)
            log.info("slack_notification_sent", title=title)
            return True
        except Exception as e:
            log.error("slack_notification_failed", error=str(e))
            return False

    def _send_discord(self, title: str, message: str) -> bool:
        """Send a Discord webhook notification."""
        try:
            payload = {
                "embeds": [
                    {
                        "title": f"Job Agent: {title}",
                        "description": message,
                        "color": 5814783,
                    }
                ]
            }
            self._post_json(self.settings.discord_webhook_url, payload)
            log.info("discord_notification_sent", title=title)
            return True
        except Exception as e:
            log.error("discord_notification_failed", error=str(e))
            return False

    def _post_json(self, url: str, payload: dict) -> None:
        """POST JSON to a webhook URL."""
        data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
