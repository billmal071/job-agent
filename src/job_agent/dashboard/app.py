"""Flask application factory for the web dashboard."""

from __future__ import annotations

from flask import Flask

from job_agent.config import Settings


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
    app.config["SECRET_KEY"] = settings.flask_secret_key
    app.config["SETTINGS"] = settings

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

    # Teardown session
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        pass  # Sessions are managed per-request in routes

    return app
