"""Discord slash command handler via HTTP Interactions API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature

from job_agent.bots.commands import BotCommandHandler
from job_agent.config import Settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

# Discord interaction types
INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2

# Discord slash command definitions
SLASH_COMMANDS = [
    {
        "name": "queue",
        "description": "List jobs awaiting review",
        "type": 1,
    },
    {
        "name": "approve",
        "description": "Approve a queued job",
        "type": 1,
        "options": [
            {
                "name": "job_id",
                "description": "The job ID to approve",
                "type": 4,  # INTEGER
                "required": True,
            }
        ],
    },
    {
        "name": "reject",
        "description": "Reject a queued job",
        "type": 1,
        "options": [
            {
                "name": "job_id",
                "description": "The job ID to reject",
                "type": 4,
                "required": True,
            }
        ],
    },
    {
        "name": "stats",
        "description": "Show job and application statistics",
        "type": 1,
    },
    {
        "name": "bookmarks",
        "description": "List bookmarked jobs",
        "type": 1,
    },
]


class DiscordInteractionHandler:
    """Handles Discord HTTP interactions (slash commands)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.handler = BotCommandHandler(settings)
        self.bot_token = settings.discord_bot_token
        self.app_id = settings.discord_application_id
        self.public_key = settings.discord_public_key

    def verify_signature(self, body: bytes, signature: str, timestamp: str) -> bool:
        """Verify Discord Ed25519 request signature."""
        if not self.public_key:
            return False

        try:
            key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key))
            key.verify(
                bytes.fromhex(signature),
                timestamp.encode() + body,
            )
            return True
        except (InvalidSignature, ValueError, Exception):
            return False

    def handle_interaction(self, payload: dict) -> dict:
        """Process an incoming Discord interaction and return a response dict."""
        interaction_type = payload.get("type")

        if interaction_type == INTERACTION_PING:
            return {"type": 1}

        if interaction_type == INTERACTION_APPLICATION_COMMAND:
            return self._handle_command(payload)

        return {"type": 4, "data": {"content": "Unknown interaction type."}}

    def _handle_command(self, payload: dict) -> dict:
        """Route a slash command to the appropriate handler."""
        data = payload.get("data", {})
        name = data.get("name", "")
        options = {o["name"]: o["value"] for o in data.get("options", [])}

        if name == "queue":
            text = self.handler.handle_queue()
        elif name == "approve":
            job_id = options.get("job_id")
            text = (
                self.handler.handle_approve(int(job_id)) if job_id else "Missing job_id"
            )
        elif name == "reject":
            job_id = options.get("job_id")
            text = (
                self.handler.handle_reject(int(job_id)) if job_id else "Missing job_id"
            )
        elif name == "stats":
            text = self.handler.handle_stats()
        elif name == "bookmarks":
            text = self.handler.handle_bookmarks()
        else:
            text = f"Unknown command: {name}"

        return {"type": 4, "data": {"content": text}}

    def register_commands(self, guild_id: str | None = None) -> bool:
        """Register slash commands with Discord. Use guild_id for instant availability."""
        if not self.bot_token or not self.app_id:
            log.error("discord_register_failed", reason="bot_token or app_id not set")
            return False

        if guild_id:
            url = f"https://discord.com/api/v10/applications/{self.app_id}/guilds/{guild_id}/commands"
        else:
            url = f"https://discord.com/api/v10/applications/{self.app_id}/commands"

        payload = json.dumps(SLASH_COMMANDS).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bot {self.bot_token}",
            },
            method="PUT",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    log.info("discord_commands_registered", guild=guild_id or "global")
                    return True
                log.error("discord_register_failed", status=resp.status)
                return False
        except urllib.error.URLError as e:
            log.error("discord_register_failed", error=str(e))
            return False
