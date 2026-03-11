"""Notification dispatchers for email, webhooks, and Telegram."""

from __future__ import annotations

from job_agent.config import Settings
from job_agent.notifications.base import Notifier
from job_agent.notifications.email_notifier import EmailNotifier
from job_agent.notifications.telegram_notifier import TelegramNotifier
from job_agent.notifications.webhook_notifier import WebhookNotifier

__all__ = [
    "EmailNotifier",
    "Notifier",
    "TelegramNotifier",
    "WebhookNotifier",
    "notify_all",
    "format_job_notification",
]


def notify_all(
    settings: Settings, title: str, message: str, event_type: str
) -> dict[str, bool]:
    """Send notifications to all enabled channels. Returns channel -> success."""
    results: dict[str, bool] = {}

    if settings.notifications.email.enabled:
        results["email"] = EmailNotifier(settings).send(title, message, event_type)

    if settings.notifications.webhook.enabled:
        results["webhook"] = WebhookNotifier(settings).send(title, message, event_type)

    if settings.notifications.telegram.enabled:
        results["telegram"] = TelegramNotifier(settings).send(
            title, message, event_type
        )

    return results


def format_job_notification(
    event: str, title: str, company: str, score: float | None = None, url: str = ""
) -> str:
    """Format a job event into a notification message."""
    parts = [f"{title} @ {company}"]
    if score is not None:
        parts.append(f"Score: {score:.2f}")
    if url:
        parts.append(url)
    return "\n".join(parts)
