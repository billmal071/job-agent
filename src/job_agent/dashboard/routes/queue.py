"""Review queue routes with HTMX approve/reject endpoints."""

from __future__ import annotations

import json

from flask import Blueprint, render_template, current_app

from job_agent.db.session import get_session
from job_agent.db.repository import JobRepository
from job_agent.db.models import JobStatus

bp = Blueprint("queue", __name__)


@bp.route("/")
def index():
    """Review queue showing queued jobs with match reasoning."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        job_repo = JobRepository(session)
        queued_jobs = job_repo.list_queued(limit=100)

        # Enrich with parsed match data
        queue_items = []
        for job in queued_jobs:
            item = {
                "job": job,
                "matched_skills": [],
                "missing_skills": [],
                "red_flags": [],
            }
            if job.match_result:
                try:
                    item["matched_skills"] = json.loads(
                        job.match_result.matched_skills or "[]"
                    )
                except (json.JSONDecodeError, TypeError):
                    pass
                try:
                    item["missing_skills"] = json.loads(
                        job.match_result.missing_skills or "[]"
                    )
                except (json.JSONDecodeError, TypeError):
                    pass
                try:
                    item["red_flags"] = json.loads(job.match_result.red_flags or "[]")
                except (json.JSONDecodeError, TypeError):
                    pass
            queue_items.append(item)

        return render_template(
            "queue/index.html",
            queue=queue_items,
            queue_count=len(queue_items),
        )
    finally:
        session.close()


@bp.route("/approve/<int:job_id>", methods=["POST"])
def approve(job_id: int):
    """Approve a queued job. Returns an HTMX HTML snippet."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        job_repo = JobRepository(session)
        job = job_repo.update_status(job_id, JobStatus.APPROVED)
        session.commit()

        if job is None:
            return '<div class="alert alert-danger">Job not found</div>', 404

        return (
            f'<div class="alert alert-success" id="job-row-{job_id}">'
            f"Approved: {job.title} @ {job.company}"
            f"</div>"
        )
    except Exception:
        session.rollback()
        return '<div class="alert alert-danger">Failed to approve job</div>', 500
    finally:
        session.close()


@bp.route("/approve-all", methods=["POST"])
def approve_all():
    """Approve all queued jobs at once. Returns an HTMX HTML snippet."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        job_repo = JobRepository(session)
        queued_jobs = job_repo.list_queued(limit=1000)
        count = 0
        for job in queued_jobs:
            job_repo.update_status(job.id, JobStatus.APPROVED)
            count += 1
        session.commit()
        return (
            f'<div class="alert alert-success">'
            f"Approved {count} job{'s' if count != 1 else ''}"
            f"</div>"
        )
    except Exception:
        session.rollback()
        return '<div class="alert alert-danger">Failed to approve jobs</div>', 500
    finally:
        session.close()


@bp.route("/reject/<int:job_id>", methods=["POST"])
def reject(job_id: int):
    """Reject a queued job. Returns an HTMX HTML snippet."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        job_repo = JobRepository(session)
        job = job_repo.update_status(job_id, JobStatus.REJECTED)
        session.commit()

        if job is None:
            return '<div class="alert alert-danger">Job not found</div>', 404

        return (
            f'<div class="alert alert-warning" id="job-row-{job_id}">'
            f"Rejected: {job.title} @ {job.company}"
            f"</div>"
        )
    except Exception:
        session.rollback()
        return '<div class="alert alert-danger">Failed to reject job</div>', 500
    finally:
        session.close()
