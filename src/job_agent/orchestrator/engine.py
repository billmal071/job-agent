"""Main orchestration engine with APScheduler integration."""

from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from job_agent.config import Settings
from job_agent.db.models import RunStatus
from job_agent.db.repository import AgentRunRepository
from job_agent.db.session import get_session
from job_agent.orchestrator.pipeline import run_pipeline
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class OrchestratorEngine:
    """Main run loop with scheduling support."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def run_once(
        self, profile_path: str, platform: str | None = None
    ) -> dict[str, int]:
        """Run the pipeline once."""
        session = get_session(self.settings)
        run_repo = AgentRunRepository(session)

        agent_run = run_repo.create(
            profile_name=profile_path,
            platform=platform or "all",
        )
        session.commit()

        try:
            # Check activity window
            now = datetime.now()
            hour = now.hour
            if not (
                self.settings.agent.activity_start_hour
                <= hour
                < self.settings.agent.activity_end_hour
            ):
                log.info("outside_activity_window", hour=hour)
                run_repo.finish(
                    agent_run.id,
                    RunStatus.CANCELLED,
                    error_message="Outside activity window",
                )
                session.commit()
                return {
                    "discovered": 0,
                    "matched": 0,
                    "applied": 0,
                    "queued": 0,
                    "skipped": 0,
                }

            stats = run_pipeline(self.settings, profile_path, platform)

            run_repo.finish(
                agent_run.id,
                RunStatus.COMPLETED,
                jobs_discovered=stats["discovered"],
                jobs_matched=stats["matched"],
                jobs_applied=stats["applied"],
                jobs_queued=stats["queued"],
                jobs_skipped=stats["skipped"],
            )
            session.commit()
            return stats

        except Exception as e:
            run_repo.finish(
                agent_run.id,
                RunStatus.FAILED,
                error_message=str(e),
            )
            session.commit()
            raise
        finally:
            session.close()

    def start(self, profile_path: str, platform: str | None = None) -> None:
        """Start the scheduled pipeline."""
        log.info(
            "scheduler_starting",
            interval=self.settings.agent.schedule_interval,
            profile=profile_path,
        )

        scheduler = BlockingScheduler()
        scheduler.add_job(
            self.run_once,
            "interval",
            minutes=self.settings.agent.schedule_interval,
            args=[profile_path, platform],
            id="pipeline",
            next_run_time=datetime.now(timezone.utc),  # Run immediately first
        )

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("scheduler_stopped")
            scheduler.shutdown()
