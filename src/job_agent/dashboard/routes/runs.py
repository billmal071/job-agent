"""Run history routes for viewing past pipeline runs."""

from __future__ import annotations

import math

from flask import Blueprint, current_app, render_template, request

from job_agent.db.models import RunStatus
from job_agent.db.repository import AgentRunRepository
from job_agent.db.session import get_session

bp = Blueprint("runs", __name__)

PER_PAGE = 25


@bp.route("/")
def index():
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)

    try:
        run_repo = AgentRunRepository(session)

        platform = request.args.get("platform") or None
        status_str = request.args.get("status") or None
        page = max(1, int(request.args.get("page", 1)))

        status_filter = None
        if status_str:
            try:
                status_filter = RunStatus(status_str)
            except ValueError:
                pass

        total = run_repo.count_filtered(platform=platform, status=status_filter)
        total_pages = max(1, math.ceil(total / PER_PAGE))
        page = min(page, total_pages)

        runs = run_repo.list_filtered(
            platform=platform,
            status=status_filter,
            limit=PER_PAGE,
            offset=(page - 1) * PER_PAGE,
        )

        return render_template(
            "runs/index.html",
            runs=runs,
            page=page,
            total_pages=total_pages,
            total=total,
            filter_platform=platform or "",
            filter_status=status_str or "",
            statuses=[s.value for s in RunStatus],
        )
    finally:
        session.close()


@bp.route("/<int:run_id>")
def detail(run_id: int):
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)

    try:
        run_repo = AgentRunRepository(session)
        run = run_repo.get_by_id(run_id)
        if not run:
            return render_template("runs/detail.html", run=None), 404

        return render_template("runs/detail.html", run=run)
    finally:
        session.close()
