"""Tests for Discord interaction handler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from job_agent.bots.discord_interactions import (
    DiscordInteractionHandler,
    INTERACTION_APPLICATION_COMMAND,
    INTERACTION_PING,
    SLASH_COMMANDS,
)
from job_agent.config import Settings


def _settings(**overrides):
    defaults = dict(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
        discord_bot_token="fake-token",
        discord_application_id="123456",
        discord_public_key="",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def test_ping_response():
    """Handler responds to PING with type 1."""
    s = _settings()
    handler = DiscordInteractionHandler(s)
    result = handler.handle_interaction({"type": INTERACTION_PING})
    assert result == {"type": 1}


def test_unknown_interaction_type():
    """Handler returns message for unknown interaction types."""
    s = _settings()
    handler = DiscordInteractionHandler(s)
    result = handler.handle_interaction({"type": 99})
    assert result["type"] == 4
    assert "Unknown" in result["data"]["content"]


def test_slash_command_queue():
    """Slash command /queue routes to handle_queue."""
    s = _settings()
    handler = DiscordInteractionHandler(s)
    handler.handler = MagicMock()
    handler.handler.handle_queue.return_value = "Queue result"

    payload = {
        "type": INTERACTION_APPLICATION_COMMAND,
        "data": {"name": "queue", "options": []},
    }
    result = handler.handle_interaction(payload)
    assert result["type"] == 4
    assert result["data"]["content"] == "Queue result"
    handler.handler.handle_queue.assert_called_once()


def test_slash_command_approve():
    """Slash command /approve routes to handle_approve with job_id."""
    s = _settings()
    handler = DiscordInteractionHandler(s)
    handler.handler = MagicMock()
    handler.handler.handle_approve.return_value = "Approved!"

    payload = {
        "type": INTERACTION_APPLICATION_COMMAND,
        "data": {
            "name": "approve",
            "options": [{"name": "job_id", "value": 42}],
        },
    }
    result = handler.handle_interaction(payload)
    assert result["data"]["content"] == "Approved!"
    handler.handler.handle_approve.assert_called_once_with(42)


def test_slash_command_reject():
    """Slash command /reject routes to handle_reject with job_id."""
    s = _settings()
    handler = DiscordInteractionHandler(s)
    handler.handler = MagicMock()
    handler.handler.handle_reject.return_value = "Rejected!"

    payload = {
        "type": INTERACTION_APPLICATION_COMMAND,
        "data": {
            "name": "reject",
            "options": [{"name": "job_id", "value": 7}],
        },
    }
    result = handler.handle_interaction(payload)
    assert result["data"]["content"] == "Rejected!"
    handler.handler.handle_reject.assert_called_once_with(7)


def test_slash_command_stats():
    """Slash command /stats routes to handle_stats."""
    s = _settings()
    handler = DiscordInteractionHandler(s)
    handler.handler = MagicMock()
    handler.handler.handle_stats.return_value = "Stats!"

    payload = {
        "type": INTERACTION_APPLICATION_COMMAND,
        "data": {"name": "stats", "options": []},
    }
    result = handler.handle_interaction(payload)
    assert result["data"]["content"] == "Stats!"


def test_slash_command_unknown():
    """Unknown slash command returns error message."""
    s = _settings()
    handler = DiscordInteractionHandler(s)
    handler.handler = MagicMock()

    payload = {
        "type": INTERACTION_APPLICATION_COMMAND,
        "data": {"name": "nonexistent", "options": []},
    }
    result = handler.handle_interaction(payload)
    assert "Unknown" in result["data"]["content"]


def test_verify_signature_valid():
    """Valid Ed25519 signature passes verification."""
    # Generate a test keypair
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_hex = public_key.public_bytes_raw().hex()

    s = _settings(discord_public_key=public_key_hex)
    handler = DiscordInteractionHandler(s)

    body = b'{"type":1}'
    timestamp = "1234567890"
    signature = private_key.sign(timestamp.encode() + body).hex()

    assert handler.verify_signature(body, signature, timestamp) is True


def test_verify_signature_invalid():
    """Invalid signature is rejected."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_hex = public_key.public_bytes_raw().hex()

    s = _settings(discord_public_key=public_key_hex)
    handler = DiscordInteractionHandler(s)

    body = b'{"type":1}'
    timestamp = "1234567890"
    # Sign with correct data but then tamper with it
    signature = private_key.sign(b"wrong data").hex()

    assert handler.verify_signature(body, signature, timestamp) is False


def test_verify_signature_no_key():
    """Missing public key rejects all signatures."""
    s = _settings(discord_public_key="")
    handler = DiscordInteractionHandler(s)
    assert handler.verify_signature(b"body", "aabb", "123") is False


@patch("job_agent.bots.discord_interactions.urllib.request.urlopen")
def test_register_commands_success(mock_urlopen):
    """Register commands calls Discord API."""
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    s = _settings()
    handler = DiscordInteractionHandler(s)
    assert handler.register_commands(guild_id="999") is True
    mock_urlopen.assert_called_once()


@patch("job_agent.bots.discord_interactions.urllib.request.urlopen")
def test_register_commands_global(mock_urlopen):
    """Register commands without guild_id uses global endpoint."""
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    s = _settings()
    handler = DiscordInteractionHandler(s)
    assert handler.register_commands() is True


def test_register_commands_no_token():
    """Register fails without bot token."""
    s = _settings(discord_bot_token="")
    handler = DiscordInteractionHandler(s)
    assert handler.register_commands() is False


def test_slash_commands_defined():
    """All expected slash commands are defined."""
    names = {cmd["name"] for cmd in SLASH_COMMANDS}
    assert names == {"queue", "approve", "reject", "stats", "bookmarks"}
