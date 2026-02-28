"""Settings page routes for credentials and thresholds."""

from __future__ import annotations

from flask import (
    Blueprint,
    render_template,
    request,
    current_app,
    redirect,
    url_for,
    flash,
)

from job_agent.db.session import get_session
from job_agent.db.repository import CredentialRepository
from job_agent.db.models import Platform
from job_agent.utils.crypto import encrypt

bp = Blueprint("settings_page", __name__)


@bp.route("/")
def index():
    """Settings overview showing current credentials and thresholds."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        cred_repo = CredentialRepository(session)
        settings = current_app.config["SETTINGS"]

        credentials = []
        for platform in Platform:
            cred = cred_repo.get(platform)
            credentials.append({
                "platform": platform.value,
                "configured": cred is not None,
                "username": cred.username if cred else "",
            })

        thresholds = {
            "auto_apply": settings.matching.auto_apply_threshold,
            "review": settings.matching.review_threshold,
        }

        return render_template(
            "settings/index.html",
            credentials=credentials,
            thresholds=thresholds,
        )
    finally:
        session.close()


@bp.route("/credentials", methods=["POST"])
def update_credentials():
    """Add or update platform credentials."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        cred_repo = CredentialRepository(session)

        platform_value = request.form.get("platform", "")
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if not platform_value or not username or not password:
            flash("All fields are required.", "danger")
            return redirect(url_for("settings_page.index"))

        try:
            platform = Platform(platform_value)
        except ValueError:
            flash(f"Invalid platform: {platform_value}", "danger")
            return redirect(url_for("settings_page.index"))

        encrypted_password = encrypt(password)
        cred_repo.upsert(
            platform=platform,
            username=username,
            encrypted_password=encrypted_password,
        )
        session.commit()
        flash(f"Credentials saved for {platform_value}.", "success")
        return redirect(url_for("settings_page.index"))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@bp.route("/thresholds", methods=["POST"])
def update_thresholds():
    """Update matching score thresholds."""
    settings = current_app.config["SETTINGS"]

    auto_apply = request.form.get("auto_apply_threshold", type=float)
    review = request.form.get("review_threshold", type=float)

    if auto_apply is not None:
        settings.matching.auto_apply_threshold = auto_apply
    if review is not None:
        settings.matching.review_threshold = review

    flash("Thresholds updated.", "success")
    return redirect(url_for("settings_page.index"))
