"""Weekly stats digest generation and email delivery."""

from __future__ import annotations

import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

from job_agent.config import Settings
from job_agent.db.models import ApplicationStatus
from job_agent.db.repository import ApplicationRepository, JobRepository
from job_agent.db.session import get_session
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def generate_digest(settings: Settings, days: int = 7) -> dict:
    """Generate stats summary for the last N days."""
    session = get_session(settings)
    try:
        job_repo = JobRepository(session)
        app_repo = ApplicationRepository(session)

        status_counts = job_repo.count_by_status()
        total_jobs = sum(status_counts.values())

        applications = app_repo.list_all(limit=10000)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        recent_apps = [
            a for a in applications if a.created_at and a.created_at >= cutoff
        ]

        submitted = sum(
            1 for a in recent_apps if a.status == ApplicationStatus.SUBMITTED
        )
        confirmed = sum(
            1 for a in recent_apps if a.status == ApplicationStatus.CONFIRMED
        )
        failed = sum(1 for a in recent_apps if a.status == ApplicationStatus.FAILED)
        pending = sum(1 for a in recent_apps if a.status == ApplicationStatus.PENDING)

        followups = app_repo.list_needing_followup(days=7)

        return {
            "period_days": days,
            "total_jobs": total_jobs,
            "status_counts": status_counts,
            "recent_applications": len(recent_apps),
            "submitted": submitted,
            "confirmed": confirmed,
            "failed": failed,
            "pending": pending,
            "followups_needed": len(followups),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    finally:
        session.close()


def format_digest_text(stats: dict) -> str:
    """Format stats dict into a readable plain-text email body."""
    lines = [
        f"Job Agent Weekly Digest ({stats['period_days']}-day summary)",
        "=" * 50,
        "",
        f"Total jobs tracked: {stats['total_jobs']}",
        "",
        "Job statuses:",
    ]
    for status, count in sorted(stats["status_counts"].items()):
        lines.append(f"  {status}: {count}")

    lines.extend(
        [
            "",
            f"Applications this period: {stats['recent_applications']}",
            f"  Submitted: {stats['submitted']}",
            f"  Confirmed: {stats['confirmed']}",
            f"  Failed: {stats['failed']}",
            f"  Pending: {stats['pending']}",
            "",
            f"Applications needing follow-up (7+ days): {stats['followups_needed']}",
            "",
            f"Generated: {stats['generated_at']}",
        ]
    )
    return "\n".join(lines)


def send_digest_email(settings: Settings, body: str) -> bool:
    """Send the digest email via SMTP. Returns True on success."""
    if not settings.smtp_user or not settings.notification_email:
        log.warning("digest_email_skipped", reason="SMTP not configured")
        return False

    msg = MIMEText(body)
    msg["Subject"] = "Job Agent Weekly Digest"
    msg["From"] = settings.smtp_user
    msg["To"] = settings.notification_email

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        log.info("digest_email_sent", to=settings.notification_email)
        return True
    except Exception as e:
        log.error("digest_email_failed", error=str(e))
        return False
