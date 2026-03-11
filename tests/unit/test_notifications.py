"""Tests for notification dispatchers (Telegram, webhook, email)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from job_agent.config import (
    NotificationsConfig,
    Settings,
    TelegramNotificationConfig,
)
from job_agent.notifications import format_job_notification, notify_all
from job_agent.notifications.telegram_notifier import TelegramNotifier


def _settings(**kwargs):
    defaults = dict(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    defaults.update(kwargs)
    return Settings(**defaults)


class TestTelegramNotifier:
    def test_skips_when_no_token(self):
        s = _settings(telegram_bot_token="", telegram_chat_id="123")
        notifier = TelegramNotifier(s)
        assert notifier.send("Title", "msg", "queued") is False

    def test_skips_when_no_chat_id(self):
        s = _settings(
            telegram_bot_token="tok",
            telegram_chat_id="",
            notifications=NotificationsConfig(
                telegram=TelegramNotificationConfig(enabled=True, triggers=["queued"]),
            ),
        )
        notifier = TelegramNotifier(s)
        assert notifier.send("Title", "msg", "queued") is False

    @patch("job_agent.notifications.telegram_notifier.urllib.request.urlopen")
    def test_sends_successfully(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        s = _settings(
            telegram_bot_token="tok123",
            telegram_chat_id="456",
            notifications=NotificationsConfig(
                telegram=TelegramNotificationConfig(enabled=True, triggers=["queued"]),
            ),
        )
        notifier = TelegramNotifier(s)
        assert notifier.send("Title", "msg", "queued") is True
        mock_urlopen.assert_called_once()

    @patch("job_agent.notifications.telegram_notifier.urllib.request.urlopen")
    def test_handles_failure(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("connection refused")

        s = _settings(
            telegram_bot_token="tok",
            telegram_chat_id="123",
            notifications=NotificationsConfig(
                telegram=TelegramNotificationConfig(enabled=True, triggers=["queued"]),
            ),
        )
        notifier = TelegramNotifier(s)
        assert notifier.send("Title", "msg", "queued") is False

    def test_skips_non_matching_trigger(self):
        s = _settings(
            telegram_bot_token="tok",
            telegram_chat_id="123",
            notifications=NotificationsConfig(
                telegram=TelegramNotificationConfig(enabled=True, triggers=["failed"]),
            ),
        )
        notifier = TelegramNotifier(s)
        # event is "queued" but triggers only has "failed"
        assert notifier.send("Title", "msg", "queued") is False


class TestNotifyAll:
    @patch("job_agent.notifications.TelegramNotifier.send", return_value=True)
    def test_dispatches_to_enabled_telegram(self, mock_send):
        s = _settings(
            telegram_bot_token="tok",
            telegram_chat_id="123",
            notifications=NotificationsConfig(
                telegram=TelegramNotificationConfig(enabled=True, triggers=["queued"]),
            ),
        )
        results = notify_all(s, "New Job", "Details", "queued")
        assert results["telegram"] is True
        mock_send.assert_called_once()

    def test_skips_disabled_channels(self):
        s = _settings(
            notifications=NotificationsConfig(
                telegram=TelegramNotificationConfig(enabled=False),
            ),
        )
        results = notify_all(s, "Title", "msg", "queued")
        assert "telegram" not in results


class TestFormatJobNotification:
    def test_format_with_score(self):
        msg = format_job_notification("queued", "Dev", "Acme", score=0.85)
        assert "Dev" in msg
        assert "Acme" in msg
        assert "0.85" in msg

    def test_format_with_url(self):
        msg = format_job_notification(
            "auto_applied", "Dev", "Co", url="https://example.com"
        )
        assert "https://example.com" in msg
