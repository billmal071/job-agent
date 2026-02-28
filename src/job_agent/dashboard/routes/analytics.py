"""Analytics page with JSON data endpoints."""

from __future__ import annotations

from flask import Blueprint, render_template, jsonify, current_app

from sqlalchemy import func, select

from job_agent.db.session import get_session
from job_agent.db.models import (
    Application,
    Job,
    MatchResult,
)

bp = Blueprint("analytics", __name__)


@bp.route("/")
def index():
    """Analytics page with charts."""
    return render_template("analytics/index.html")


@bp.route("/data/scores")
def data_scores():
    """JSON endpoint for match score distribution."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        stmt = select(MatchResult.score).order_by(MatchResult.score)
        scores = list(session.scalars(stmt).all())

        # Build histogram buckets (0-10, 10-20, ..., 90-100)
        buckets = {f"{i}-{i + 10}": 0 for i in range(0, 100, 10)}
        for score in scores:
            bucket_idx = min(int(score // 10) * 10, 90)
            key = f"{bucket_idx}-{bucket_idx + 10}"
            buckets[key] += 1

        return jsonify(
            {
                "total": len(scores),
                "average": round(sum(scores) / len(scores), 2) if scores else 0,
                "min": round(min(scores), 2) if scores else 0,
                "max": round(max(scores), 2) if scores else 0,
                "distribution": buckets,
                "raw_scores": [round(s, 2) for s in scores],
            }
        )
    finally:
        session.close()


@bp.route("/data/timeline")
def data_timeline():
    """JSON endpoint for application timeline (applications per day)."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        stmt = (
            select(
                func.date(Application.created_at).label("date"),
                func.count(Application.id).label("count"),
            )
            .group_by(func.date(Application.created_at))
            .order_by(func.date(Application.created_at))
        )
        rows = session.execute(stmt).all()

        timeline = [{"date": str(row.date), "count": row.count} for row in rows]

        # Also compute job discovery timeline
        job_stmt = (
            select(
                func.date(Job.discovered_at).label("date"),
                func.count(Job.id).label("count"),
            )
            .group_by(func.date(Job.discovered_at))
            .order_by(func.date(Job.discovered_at))
        )
        job_rows = session.execute(job_stmt).all()
        job_timeline = [
            {"date": str(row.date), "count": row.count} for row in job_rows
        ]

        return jsonify(
            {
                "applications": timeline,
                "discoveries": job_timeline,
            }
        )
    finally:
        session.close()
