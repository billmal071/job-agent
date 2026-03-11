"""Application listing, CSV export, and retry routes."""

from __future__ import annotations

import csv
import io

from pathlib import Path

from flask import Blueprint, render_template, request, current_app, Response, send_file

from job_agent.db.session import get_session
from job_agent.db.repository import ApplicationRepository, JobRepository
from job_agent.db.models import Application, ApplicationStatus, JobStatus

bp = Blueprint("applications", __name__)


@bp.route("/")
def index():
    """List all submitted applications with status."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        app_repo = ApplicationRepository(session)

        status_filter = request.args.get("status")
        status = None
        if status_filter:
            try:
                status = ApplicationStatus(status_filter)
            except ValueError:
                pass

        applications = app_repo.list_all(status=status)

        return render_template(
            "applications/index.html",
            applications=applications,
            statuses=ApplicationStatus,
            current_status=status_filter or "",
        )
    finally:
        session.close()


@bp.route("/export")
def export():
    """CSV export of all applications."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        app_repo = ApplicationRepository(session)
        applications = app_repo.list_all(limit=10000)

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Application ID",
                "Job ID",
                "Job Title",
                "Company",
                "Platform",
                "Status",
                "Applied At",
                "Resume Path",
                "Cover Letter Path",
                "Error Message",
                "Created At",
            ]
        )

        for app in applications:
            job = app.job
            writer.writerow(
                [
                    app.id,
                    app.job_id,
                    job.title if job else "",
                    job.company if job else "",
                    job.platform.value if job else "",
                    app.status.value,
                    app.applied_at.isoformat() if app.applied_at else "",
                    app.resume_path,
                    app.cover_letter_path,
                    app.error_message,
                    app.created_at.isoformat() if app.created_at else "",
                ]
            )

        csv_content = output.getvalue()
        output.close()

        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=applications.csv"},
        )
    finally:
        session.close()


@bp.route("/<int:app_id>/download-resume")
def download_resume(app_id: int):
    """Download the tailored resume for an application."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        application = session.get(Application, app_id)
        if application is None:
            return "Application not found", 404
        if not application.resume_path:
            return "No resume available for this application", 404

        resume_file = Path(application.resume_path)
        if not resume_file.exists():
            return "Resume file not found on disk", 404

        return send_file(
            str(resume_file),
            as_attachment=True,
            download_name=f"resume_{app_id}{resume_file.suffix}",
        )
    finally:
        session.close()


@bp.route("/<int:app_id>/download-cover-letter")
def download_cover_letter(app_id: int):
    """Download the cover letter for an application."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        application = session.get(Application, app_id)
        if application is None:
            return "Application not found", 404
        if not application.cover_letter_path:
            return "No cover letter available for this application", 404

        cl_file = Path(application.cover_letter_path)
        if not cl_file.exists():
            return "Cover letter file not found on disk", 404

        return send_file(
            str(cl_file),
            as_attachment=True,
            download_name=f"cover_letter_{app_id}{cl_file.suffix}",
        )
    finally:
        session.close()


@bp.route("/retry/<int:app_id>", methods=["POST"])
def retry(app_id: int):
    """Retry a failed application by resetting its status.

    Resets the application to PENDING and the job to APPROVED so the
    apply-approved pipeline will pick it up on the next run.
    """
    session = get_session(current_app.config["SETTINGS"])
    try:
        job_repo = JobRepository(session)
        application = session.get(Application, app_id)
        if application is None:
            return '<div class="alert alert-danger">Application not found</div>', 404

        if application.status not in (
            ApplicationStatus.FAILED,
            ApplicationStatus.WITHDRAWN,
        ):
            return (
                '<div class="alert alert-warning">'
                f"Cannot retry: status is {application.status.value}"
                "</div>",
                400,
            )

        # Reset application
        application.status = ApplicationStatus.PENDING
        application.error_message = ""
        application.applied_at = None

        # Reset job status to APPROVED so pipeline picks it up
        job = job_repo.get_by_id(application.job_id)
        if job:
            job.status = JobStatus.APPROVED

        session.commit()

        job_title = job.title if job else "Unknown"
        return (
            f'<div class="alert alert-success">'
            f'Retrying: {job_title}. Run "Apply Approved" to process.'
            f"</div>"
        )
    except Exception:
        session.rollback()
        return '<div class="alert alert-danger">Failed to retry application</div>', 500
    finally:
        session.close()
