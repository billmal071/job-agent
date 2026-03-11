"""Discord interactions webhook endpoint."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

bp = Blueprint("discord_webhook", __name__)


@bp.route("/interactions", methods=["POST"])
def interactions():
    """Handle Discord interaction webhooks (slash commands)."""
    settings = current_app.config["SETTINGS"]

    if not settings.discord_public_key:
        return jsonify(error="Discord not configured"), 503

    from job_agent.bots.discord_interactions import DiscordInteractionHandler

    handler = DiscordInteractionHandler(settings)

    # Verify signature
    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")
    body = request.get_data()

    if not handler.verify_signature(body, signature, timestamp):
        return "Invalid signature", 401

    payload = request.get_json(silent=True) or {}
    result = handler.handle_interaction(payload)
    return jsonify(result)
