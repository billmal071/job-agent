"""Review queue manager for manual approval/rejection."""

from __future__ import annotations

from job_agent.config import Settings
from job_agent.db.models import ApplicationStatus, JobStatus
from job_agent.db.repository import ApplicationRepository, JobRepository
from job_agent.db.session import get_session
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class ReviewQueueManager:
    """Manages the review queue for jobs requiring manual approval."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def get_queue(self) -> list[dict]:
        """Get all queued jobs with their match results."""
        session = get_session(self.settings)
        try:
            job_repo = JobRepository(session)
            jobs = job_repo.list_queued()
            queue = []
            for job in jobs:
                item = {
                    "job": job,
                    "match_result": job.match_result,
                }
                queue.append(item)
            return queue
        finally:
            session.close()

    def approve(self, job_id: int) -> bool:
        """Approve a queued job for application."""
        session = get_session(self.settings)
        try:
            job_repo = JobRepository(session)
            job = job_repo.get_by_id(job_id)
            if not job or job.status != JobStatus.QUEUED:
                return False

            job.status = JobStatus.APPROVED
            session.commit()
            log.info("job_approved", job_id=job_id)
            return True
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()

    def reject(self, job_id: int) -> bool:
        """Reject a queued job."""
        session = get_session(self.settings)
        try:
            job_repo = JobRepository(session)
            job = job_repo.get_by_id(job_id)
            if not job or job.status != JobStatus.QUEUED:
                return False

            job.status = JobStatus.REJECTED
            session.commit()
            log.info("job_rejected", job_id=job_id)
            return True
        except Exception:
            session.rollback()
            return False
        finally:
            session.close()

    def process_approved(self) -> int:
        """Process all approved jobs (apply to them). Returns count applied."""
        session = get_session(self.settings)
        applied = 0
        try:
            job_repo = JobRepository(session)
            app_repo = ApplicationRepository(session)
            jobs = job_repo.list_by_status(JobStatus.APPROVED)

            for job in jobs:
                # Create an application record - actual apply happens in pipeline
                app_repo.create(
                    job_id=job.id,
                    status=ApplicationStatus.PENDING,
                )
                applied += 1

            session.commit()
            return applied
        except Exception:
            session.rollback()
            return applied
        finally:
            session.close()
