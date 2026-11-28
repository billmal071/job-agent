"""Flask application factory for the web dashboard."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from flask import Flask, jsonify

from job_agent.config import Settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def create_app(settings: Settings | None = None) -> Flask:
    """Create and configure the Flask application."""
    if settings is None:
        from job_agent.config import load_settings

        settings = load_settings()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    if settings.flask_secret_key == "change-me":
        log.warning(
            "flask_secret_key is the default 'change-me' value; generating a "
            "random key for this process. Sessions will not survive restarts. "
            "Set JOB_AGENT_FLASK_SECRET_KEY (or flask_secret_key in config) "
            "for production use."
        )
        app.config["SECRET_KEY"] = secrets.token_hex(32)
    else:
        app.config["SECRET_KEY"] = settings.flask_secret_key
    app.config["SETTINGS"] = settings

    # Custom Jinja2 filters
    def from_json(value):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []

    app.jinja_env.filters["from_json"] = from_json
    app.jinja_env.globals["now"] = lambda: datetime.now(timezone.utc)

    # Make settings available in templates
    @app.context_processor
    def inject_settings():
        return {"settings": settings}

    # Register routes
    from job_agent.dashboard.routes.overview import bp as overview_bp
    from job_agent.dashboard.routes.jobs import bp as jobs_bp
    from job_agent.dashboard.routes.queue import bp as queue_bp
    from job_agent.dashboard.routes.applications import bp as applications_bp
    from job_agent.dashboard.routes.outreach import bp as outreach_bp
    from job_agent.dashboard.routes.analytics import bp as analytics_bp
    from job_agent.dashboard.routes.settings_page import bp as settings_bp

    app.register_blueprint(overview_bp)
    app.register_blueprint(jobs_bp, url_prefix="/jobs")
    app.register_blueprint(queue_bp, url_prefix="/queue")
    app.register_blueprint(applications_bp, url_prefix="/applications")
    app.register_blueprint(outreach_bp, url_prefix="/outreach")
    app.register_blueprint(analytics_bp, url_prefix="/analytics")
    app.register_blueprint(settings_bp, url_prefix="/settings")

    from job_agent.dashboard.routes.actions import bp as actions_bp
    from job_agent.dashboard.routes.discord_webhook import bp as discord_bp
    from job_agent.dashboard.routes.runs import bp as runs_bp

    app.register_blueprint(actions_bp, url_prefix="/actions")
    app.register_blueprint(discord_bp, url_prefix="/discord")
    app.register_blueprint(runs_bp, url_prefix="/runs")

    # Health check
    @app.route("/health")
    def health():
        try:
            app_version = version("job-agent")
        except PackageNotFoundError:
            app_version = "unknown"
        return jsonify({"status": "ok", "version": app_version})

    # Teardown session
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        pass  # Sessions are managed per-request in routes

    return app
