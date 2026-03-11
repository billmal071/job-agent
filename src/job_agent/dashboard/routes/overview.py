"""Overview dashboard routes."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, render_template, current_app

from job_agent.db.session import get_session
from job_agent.db.repository import (
    AgentRunRepository,
    ApplicationRepository,
    JobRepository,
)
from job_agent.db.models import ApplicationStatus, JobStatus

PROFILES_DIR = Path("config/profiles")

bp = Blueprint("overview", __name__)


@bp.route("/")
def index():
    """Overview page with summary cards and recent activity timeline."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        job_repo = JobRepository(session)
        app_repo = ApplicationRepository(session)
        run_repo = AgentRunRepository(session)

        # Summary counts
        status_counts = job_repo.count_by_status()
        total_jobs = sum(status_counts.values())
        queue_size = status_counts.get(JobStatus.QUEUED.value, 0)

        applications = app_repo.list_all()
        total_applications = len(applications)
        submitted = sum(
            1 for a in applications if a.status == ApplicationStatus.SUBMITTED
        )
        confirmed = sum(
            1 for a in applications if a.status == ApplicationStatus.CONFIRMED
        )
        failed = sum(1 for a in applications if a.status == ApplicationStatus.FAILED)
        success_rate = (
            round((submitted + confirmed) / total_applications * 100, 1)
            if total_applications > 0
            else 0.0
        )

        # Follow-up reminders
        followups = app_repo.list_needing_followup(days=7)

        # Recent activity from agent runs
        recent_runs = run_repo.get_latest(limit=20)

        # Available profiles for pipeline actions
        profiles = (
            sorted(
                f.name for f in PROFILES_DIR.glob("*.yaml") if f.name != "example.yaml"
            )
            if PROFILES_DIR.is_dir()
            else []
        )

        return render_template(
            "overview/index.html",
            total_jobs=total_jobs,
            total_applications=total_applications,
            queue_size=queue_size,
            success_rate=success_rate,
            submitted=submitted,
            confirmed=confirmed,
            failed=failed,
            status_counts=status_counts,
            recent_runs=recent_runs,
            followups=followups,
            profiles=profiles,
        )
    finally:
        session.close()
