"""Shared command handler for bot adapters (Telegram, Discord)."""

from __future__ import annotations

from job_agent.config import Settings
from job_agent.db.models import JobStatus
from job_agent.db.repository import ApplicationRepository, JobRepository
from job_agent.db.session import get_session
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class BotCommandHandler:
    """Processes bot commands against the database. Each method opens/closes its own session."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def handle_queue(self, limit: int = 10) -> str:
        """List queued jobs awaiting review."""
        session = get_session(self.settings)
        try:
            repo = JobRepository(session)
            jobs = repo.list_queued(limit=limit)
            if not jobs:
                return "No jobs in the review queue."

            lines = [f"Review Queue ({len(jobs)} jobs):"]
            for job in jobs:
                score = ""
                if job.match_result:
                    score = f" [{job.match_result.score:.2f}]"
                lines.append(f"  #{job.id} {job.title} @ {job.company}{score}")
            return "\n".join(lines)
        finally:
            session.close()

    def handle_approve(self, job_id: int) -> str:
        """Approve a queued job."""
        session = get_session(self.settings)
        try:
            repo = JobRepository(session)
            job = repo.get_by_id(job_id)
            if job is None:
                return f"Job #{job_id} not found."
            if job.status != JobStatus.QUEUED:
                return f"Job #{job_id} is not queued (status: {job.status.value})."
            repo.update_status(job_id, JobStatus.APPROVED)
            session.commit()
            return f"Approved: {job.title} @ {job.company}"
        except Exception as e:
            session.rollback()
            log.error("bot_approve_failed", job_id=job_id, error=str(e))
            return f"Failed to approve job #{job_id}."
        finally:
            session.close()

    def handle_reject(self, job_id: int) -> str:
        """Reject a queued job."""
        session = get_session(self.settings)
        try:
            repo = JobRepository(session)
            job = repo.get_by_id(job_id)
            if job is None:
                return f"Job #{job_id} not found."
            if job.status != JobStatus.QUEUED:
                return f"Job #{job_id} is not queued (status: {job.status.value})."
            repo.update_status(job_id, JobStatus.REJECTED)
            session.commit()
            return f"Rejected: {job.title} @ {job.company}"
        except Exception as e:
            session.rollback()
            log.error("bot_reject_failed", job_id=job_id, error=str(e))
            return f"Failed to reject job #{job_id}."
        finally:
            session.close()

    def handle_stats(self) -> str:
        """Show job and application statistics."""
        session = get_session(self.settings)
        try:
            job_repo = JobRepository(session)
            app_repo = ApplicationRepository(session)

            status_counts = job_repo.count_by_status()
            total = sum(status_counts.values())
            apps = app_repo.list_all(limit=10000)
            followups = app_repo.list_needing_followup(days=7)

            lines = [
                "Stats Summary:",
                f"  Total jobs: {total}",
            ]
            for status, count in sorted(status_counts.items()):
                lines.append(f"  {status}: {count}")
            lines.append(f"  Applications: {len(apps)}")
            lines.append(f"  Need follow-up: {len(followups)}")
            return "\n".join(lines)
        finally:
            session.close()

    def handle_bookmarks(self, limit: int = 10) -> str:
        """List bookmarked jobs."""
        session = get_session(self.settings)
        try:
            repo = JobRepository(session)
            jobs = repo.list_all(bookmarked=True, limit=limit)
            if not jobs:
                return "No bookmarked jobs."

            lines = [f"Bookmarked Jobs ({len(jobs)}):"]
            for job in jobs:
                lines.append(
                    f"  #{job.id} {job.title} @ {job.company} [{job.status.value}]"
                )
            return "\n".join(lines)
        finally:
            session.close()

    def handle_help(self) -> str:
        """Return available commands."""
        return (
            "Available commands:\n"
            "  /queue - List jobs awaiting review\n"
            "  /approve <id> - Approve a queued job\n"
            "  /reject <id> - Reject a queued job\n"
            "  /stats - Show statistics\n"
            "  /bookmarks - List bookmarked jobs\n"
            "  /help - Show this message"
        )

    def route_command(self, text: str) -> str:
        """Parse a command string and route to the appropriate handler."""
        text = text.strip()
        if not text.startswith("/"):
            return self.handle_help()

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]  # strip @botname suffix
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/queue":
            return self.handle_queue()
        elif cmd == "/approve":
            return self._parse_id_command(arg, self.handle_approve)
        elif cmd == "/reject":
            return self._parse_id_command(arg, self.handle_reject)
        elif cmd == "/stats":
            return self.handle_stats()
        elif cmd == "/bookmarks":
            return self.handle_bookmarks()
        elif cmd in ("/help", "/start"):
            return self.handle_help()
        else:
            return f"Unknown command: {cmd}\n\n" + self.handle_help()

    def _parse_id_command(self, arg: str, handler) -> str:
        """Parse a job ID argument and call the handler."""
        if not arg:
            return "Please provide a job ID. Example: /approve 42"
        try:
            job_id = int(arg)
        except ValueError:
            return f"Invalid job ID: {arg}"
        return handler(job_id)
