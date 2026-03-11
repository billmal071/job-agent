"""Application listing and CSV export routes."""

from __future__ import annotations

import csv
import io

from flask import Blueprint, render_template, request, current_app, Response

from job_agent.db.session import get_session
from job_agent.db.repository import ApplicationRepository
from job_agent.db.models import ApplicationStatus

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
