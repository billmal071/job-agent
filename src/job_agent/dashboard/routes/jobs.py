"""Job listing and detail routes."""

from __future__ import annotations

import json

from flask import Blueprint, render_template, request, current_app

from job_agent.db.session import get_session
from job_agent.db.repository import JobRepository, MatchResultRepository
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

        jobs = job_repo.list_all(
            platform=platform,
            status=status,
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
            page=page,
        )
    finally:
        session.close()


@bp.route("/<int:job_id>")
def detail(job_id: int):
    """Job detail page with match result."""
    session = get_session(current_app.config["SETTINGS"])
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

        return render_template(
            "jobs/detail.html",
            job=job,
            match_result=match_result,
            matched_skills=matched_skills,
            missing_skills=missing_skills,
            red_flags=red_flags,
        )
    finally:
        session.close()
