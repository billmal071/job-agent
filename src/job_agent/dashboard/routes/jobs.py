"""Job listing and detail routes."""

from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, render_template, request, current_app, send_file

from job_agent.db.session import get_session
from job_agent.db.repository import JobRepository
from job_agent.db.models import JobStatus, Platform

bp = Blueprint("jobs", __name__)


@bp.route("/")
def index():
    """Filterable table of all jobs."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        job_repo = JobRepository(session)

        # Filter parameters
        platform_filter = request.args.get("platform")
        status_filter = request.args.get("status")
        bookmark_filter = request.args.get("bookmarked")
        score_min = request.args.get("score_min", type=float)
        score_max = request.args.get("score_max", type=float)
        page = request.args.get("page", 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page

        platform = None
        if platform_filter:
            try:
                platform = Platform(platform_filter)
            except ValueError:
                pass

        status = None
        if status_filter:
            try:
                status = JobStatus(status_filter)
            except ValueError:
                pass

        bookmarked = None
        if bookmark_filter == "1":
            bookmarked = True

        jobs = job_repo.list_all(
            platform=platform,
            status=status,
            bookmarked=bookmarked,
            limit=per_page,
            offset=offset,
        )

        # Apply score filtering in Python (requires match_result join)
        if score_min is not None or score_max is not None:
            filtered = []
            for job in jobs:
                if job.match_result is None:
                    continue
                score = job.match_result.score
                if score_min is not None and score < score_min:
                    continue
                if score_max is not None and score > score_max:
                    continue
                filtered.append(job)
            jobs = filtered

        return render_template(
            "jobs/index.html",
            jobs=jobs,
            platforms=Platform,
            statuses=JobStatus,
            current_platform=platform_filter or "",
            current_status=status_filter or "",
            current_score_min=score_min,
            current_score_max=score_max,
            current_bookmarked=bookmark_filter or "",
            page=page,
        )
    finally:
        session.close()


@bp.route("/<int:job_id>/bookmark", methods=["POST"])
def toggle_bookmark(job_id: int):
    """Toggle bookmark on a job. Returns HTMX snippet."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        job_repo = JobRepository(session)
        job = job_repo.toggle_bookmark(job_id)
        session.commit()

        if job is None:
            return '<span class="text-muted">Not found</span>', 404

        icon = "bi-bookmark-fill" if job.bookmarked else "bi-bookmark"
        cls = "btn-warning" if job.bookmarked else "btn-ghost"
        return (
            f'<button class="btn {cls} btn-sm" '
            f'hx-post="/jobs/{job_id}/bookmark" '
            f'hx-swap="outerHTML" title="Toggle bookmark">'
            f'<i class="bi {icon}"></i></button>'
        )
    except Exception:
        session.rollback()
        return '<span class="text-muted">Error</span>', 500
    finally:
        session.close()


@bp.route("/<int:job_id>")
def detail(job_id: int):
    """Job detail page with match result."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        job_repo = JobRepository(session)
        job = job_repo.get_by_id(job_id)

        if job is None:
            return render_template("errors/404.html", message="Job not found"), 404

        match_result = job.match_result
        matched_skills = []
        missing_skills = []
        red_flags = []

        if match_result:
            try:
                matched_skills = json.loads(match_result.matched_skills or "[]")
            except (json.JSONDecodeError, TypeError):
                matched_skills = []
            try:
                missing_skills = json.loads(match_result.missing_skills or "[]")
            except (json.JSONDecodeError, TypeError):
                missing_skills = []
            try:
                red_flags = json.loads(match_result.red_flags or "[]")
            except (json.JSONDecodeError, TypeError):
                red_flags = []

        # Check for existing tailored resume
        resume_dir = Path(settings.data_dir / "resumes")
        safe_name = f"{job.company}_{job.external_id}".replace(" ", "_")[:60]
        existing_pdf = resume_dir / f"{safe_name}.pdf"
        existing_md = resume_dir / f"{safe_name}.md"

        return render_template(
            "jobs/detail.html",
            job=job,
            match=match_result,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            red_flags=red_flags,
            has_resume_pdf=existing_pdf.exists(),
            has_resume_md=existing_md.exists(),
        )
    finally:
        session.close()


@bp.route("/<int:job_id>/preview-resume", methods=["POST"])
def preview_resume(job_id: int):
    """Generate a tailored resume preview (markdown) via AI."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        job_repo = JobRepository(session)
        job = job_repo.get_by_id(job_id)
        if job is None:
            return '<div class="alert alert-danger">Job not found</div>', 404

        matched_skills: list[str] = []
        if job.match_result and job.match_result.matched_skills:
            try:
                matched_skills = json.loads(job.match_result.matched_skills)
            except (ValueError, TypeError):
                pass

        from job_agent.ai.client import AIClient
        from job_agent.ai.resume_tailor import ResumeTailor
        from job_agent.platforms.base import JobPosting

        ai_client = AIClient(settings)
        tailor = ResumeTailor(ai_client, settings)

        posting = JobPosting(
            external_id=job.external_id,
            platform=job.platform,
            title=job.title,
            company=job.company,
            location=job.location,
            description=job.description or "",
            url=job.url,
        )

        tailored_md = tailor.tailor(posting, matched_skills)

        # Save markdown draft for editing
        resume_dir = Path(settings.data_dir / "resumes")
        resume_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{job.company}_{job.external_id}".replace(" ", "_")[:60]
        md_path = resume_dir / f"{safe_name}.md"
        md_path.write_text(tailored_md)

        # Return editable form
        return render_template(
            "jobs/_resume_editor.html",
            job=job,
            resume_md=tailored_md,
        )
    except Exception as e:
        return f'<div class="alert alert-danger">Error: {e}</div>', 500
    finally:
        session.close()


@bp.route("/<int:job_id>/save-resume", methods=["POST"])
def save_resume(job_id: int):
    """Save edited markdown and generate PDF."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        job_repo = JobRepository(session)
        job = job_repo.get_by_id(job_id)
        if job is None:
            return '<div class="alert alert-danger">Job not found</div>', 404

        resume_md = request.form.get("resume_md", "")
        if not resume_md.strip():
            return '<div class="alert alert-danger">Resume content is empty</div>', 400

        from job_agent.ai.client import AIClient
        from job_agent.ai.resume_tailor import ResumeTailor

        ai_client = AIClient(settings)
        tailor = ResumeTailor(ai_client, settings)

        resume_dir = Path(settings.data_dir / "resumes")
        resume_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{job.company}_{job.external_id}".replace(" ", "_")[:60]

        # Save markdown
        md_path = resume_dir / f"{safe_name}.md"
        md_path.write_text(resume_md)

        # Generate PDF
        pdf_path = str(resume_dir / f"{safe_name}.pdf")
        tailor.generate_pdf(resume_md, pdf_path)

        return (
            '<div class="alert alert-success">'
            "Resume saved and PDF generated. "
            f'<a href="/jobs/{job_id}/download-resume" class="alert-link" target="_blank">'
            "Download PDF</a>"
            "</div>"
        )
    except Exception as e:
        return f'<div class="alert alert-danger">Error: {e}</div>', 500
    finally:
        session.close()


@bp.route("/<int:job_id>/download-resume")
def download_resume(job_id: int):
    """Download the generated PDF resume for a job."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        job_repo = JobRepository(session)
        job = job_repo.get_by_id(job_id)
        if job is None:
            return "Job not found", 404

        resume_dir = Path(settings.data_dir / "resumes")
        safe_name = f"{job.company}_{job.external_id}".replace(" ", "_")[:60]
        pdf_path = resume_dir / f"{safe_name}.pdf"

        if not pdf_path.exists():
            return "Resume PDF not found. Generate a preview first.", 404

        return send_file(
            str(pdf_path),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"resume_{safe_name}.pdf",
        )
    finally:
        session.close()
