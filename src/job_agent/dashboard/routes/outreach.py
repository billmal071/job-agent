"""Outreach message listing with response tracking."""

from __future__ import annotations

from flask import Blueprint, render_template, current_app

from job_agent.db.session import get_session
from job_agent.db.repository import OutreachRepository
from job_agent.db.models import OutreachStatus

bp = Blueprint("outreach", __name__)


@bp.route("/")
def index():
    """Outreach message list with response tracking."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        outreach_repo = OutreachRepository(session)
        messages = outreach_repo.list_all(limit=200)

        # Compute summary stats
        total = len(messages)
        sent = sum(1 for m in messages if m.status != OutreachStatus.PENDING)
        accepted = sum(1 for m in messages if m.status == OutreachStatus.ACCEPTED)
        replied = sum(1 for m in messages if m.status == OutreachStatus.REPLIED)
        follow_ups = sum(
            1 for m in messages if m.status == OutreachStatus.FOLLOW_UP_SENT
        )
        failed = sum(1 for m in messages if m.status == OutreachStatus.FAILED)
        response_rate = (
            round((accepted + replied) / sent * 100, 1) if sent > 0 else 0.0
        )

        stats = {
            "total": total,
            "sent": sent,
            "accepted": accepted,
            "replied": replied,
            "follow_ups": follow_ups,
            "failed": failed,
            "response_rate": response_rate,
        }

        return render_template(
            "outreach/index.html",
            messages=messages,
            stats=stats,
        )
    finally:
        session.close()
