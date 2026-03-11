"""Tests for Telegram bot message parsing and security."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from job_agent.bots.telegram_bot import TelegramBot
from job_agent.config import Settings


def _settings():
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
        telegram_bot_token="test-token",
        telegram_chat_id="12345",
    )


def test_handle_update_routes_command():
    """Bot routes message text through command handler."""
    s = _settings()
    bot = TelegramBot(s)
    bot.handler = MagicMock()
    bot.handler.route_command.return_value = "test response"
    bot._send_reply = MagicMock(return_value=True)

    update = {
        "update_id": 1,
        "message": {
            "chat": {"id": 12345},
            "text": "/help",
        },
    }
    bot._handle_update(update)

    bot.handler.route_command.assert_called_once_with("/help")
    bot._send_reply.assert_called_once_with("12345", "test response")


def test_handle_update_ignores_unauthorized():
    """Bot ignores messages from unauthorized chat_id."""
    s = _settings()
    bot = TelegramBot(s)
    bot.handler = MagicMock()
    bot._send_reply = MagicMock()

    update = {
        "update_id": 2,
        "message": {
            "chat": {"id": 99999},  # Wrong chat_id
            "text": "/queue",
        },
    }
    bot._handle_update(update)

    bot.handler.route_command.assert_not_called()
    bot._send_reply.assert_not_called()


def test_handle_update_ignores_empty_message():
    """Bot ignores updates without text."""
    s = _settings()
    bot = TelegramBot(s)
    bot.handler = MagicMock()

    update = {"update_id": 3, "message": {"chat": {"id": 12345}}}
    bot._handle_update(update)

    bot.handler.route_command.assert_not_called()


@patch("job_agent.bots.telegram_bot.urllib.request.urlopen")
def test_poll_returns_updates(mock_urlopen):
    """Poll parses getUpdates response."""
    import json

    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = json.dumps(
        {
            "ok": True,
            "result": [{"update_id": 1, "message": {"text": "/help"}}],
        }
    ).encode()
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    s = _settings()
    bot = TelegramBot(s)
    updates = bot._poll(0)
    assert len(updates) == 1
    assert updates[0]["update_id"] == 1


@patch("job_agent.bots.telegram_bot.urllib.request.urlopen")
def test_send_reply(mock_urlopen):
    """Send reply calls Telegram sendMessage API."""
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    s = _settings()
    bot = TelegramBot(s)
    result = bot._send_reply("12345", "Hello")
    assert result is True
    mock_urlopen.assert_called_once()
