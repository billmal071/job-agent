"""Email notification sender via SMTP."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from job_agent.config import Settings
from job_agent.notifications.base import Notifier
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class EmailNotifier(Notifier):
    """Send notifications via email."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.triggers = settings.notifications.email.triggers

    def send(self, title: str, message: str, event_type: str = "") -> bool:
        if not self.should_notify(event_type, self.triggers):
            return False

        if not self.settings.smtp_user or not self.settings.notification_email:
            log.warning("email_not_configured")
            return False

        try:
            msg = MIMEText(message)
            msg["Subject"] = f"[Job Agent] {title}"
            msg["From"] = self.settings.smtp_user
            msg["To"] = self.settings.notification_email

            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port) as server:
                server.starttls()
                server.login(self.settings.smtp_user, self.settings.smtp_password)
                server.send_message(msg)

            log.info("email_sent", to=self.settings.notification_email, title=title)
            return True
        except Exception as e:
            log.error("email_failed", error=str(e))
            return False
