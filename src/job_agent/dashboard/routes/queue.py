"""Review queue routes with HTMX approve/reject endpoints."""

from __future__ import annotations

from flask import Blueprint, render_template, current_app, request, jsonify

from job_agent.db.session import get_session
from job_agent.db.repository import JobRepository
from job_agent.db.models import JobStatus
from job_agent.utils.json_helpers import parse_json_list
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

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
                item["matched_skills"] = parse_json_list(
                    job.match_result.matched_skills
                )
                item["missing_skills"] = parse_json_list(
                    job.match_result.missing_skills
                )
                item["red_flags"] = parse_json_list(job.match_result.red_flags)
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
    except Exception as e:
        session.rollback()
        log.warning("approve_failed", job_id=job_id, error=str(e))
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
    except Exception as e:
        session.rollback()
        log.warning("approve_all_failed", error=str(e))
        return '<div class="alert alert-danger">Failed to approve jobs</div>', 500
    finally:
        session.close()


@bp.route("/bulk-action", methods=["POST"])
def bulk_action():
    """Approve or reject multiple queued jobs. Expects JSON {action, job_ids}."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        job_ids = data.get("job_ids", [])

        if action not in ("approve", "reject"):
            return jsonify(ok=False, message="Invalid action"), 400
        if not job_ids or not isinstance(job_ids, list):
            return jsonify(ok=False, message="No jobs selected"), 400

        target_status = (
            JobStatus.APPROVED if action == "approve" else JobStatus.REJECTED
        )
        job_repo = JobRepository(session)
        count = 0
        for jid in job_ids:
            result = job_repo.update_status(jid, target_status)
            if result is not None:
                count += 1
        session.commit()

        verb = "Approved" if action == "approve" else "Rejected"
        return jsonify(
            ok=True, message=f"{verb} {count} job{'s' if count != 1 else ''}"
        )
    except Exception as e:
        session.rollback()
        log.warning("bulk_action_failed", error=str(e))
        return jsonify(ok=False, message="Failed to process bulk action"), 500
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
    except Exception as e:
        session.rollback()
        log.warning("reject_failed", job_id=job_id, error=str(e))
        return '<div class="alert alert-danger">Failed to reject job</div>', 500
    finally:
        session.close()
