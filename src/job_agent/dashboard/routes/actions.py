"""Action routes for triggering pipeline operations from the dashboard."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, request
from markupsafe import escape

from job_agent.dashboard.tasks import task_runner

bp = Blueprint("actions", __name__)

PROFILES_DIR = Path("config/profiles")


def _get_profiles() -> list[str]:
    """Return list of available profile YAML filenames (excluding example)."""
    if not PROFILES_DIR.is_dir():
        return []
    return sorted(
        f.name for f in PROFILES_DIR.glob("*.yaml") if f.name != "example.yaml"
    )


def _resolve_profile_path(profile_name: str | None = None) -> str:
    """Resolve a profile name to its file path."""
    profiles = _get_profiles()
    if profile_name and profile_name in profiles:
        return str(PROFILES_DIR / profile_name)
    if profiles:
        return str(PROFILES_DIR / profiles[0])
    return ""


@bp.route("/apply-approved", methods=["POST"])
def apply_approved():
    """Start apply-approved in a background thread."""
    settings = current_app.config["SETTINGS"]
    profile_path = _resolve_profile_path(request.form.get("profile"))

    from job_agent.orchestrator.pipeline import apply_approved as _apply_approved

    task_id = task_runner.run("Apply Approved", _apply_approved, settings, profile_path)

    return _status_snippet(task_id)


@bp.route("/run-pipeline", methods=["POST"])
def run_pipeline():
    """Start the full pipeline in a background thread."""
    settings = current_app.config["SETTINGS"]
    profile_name = request.form.get("profile")
    platform = request.form.get("platform") or None
    profile_path = _resolve_profile_path(profile_name)

    if not profile_path:
        return '<div class="alert alert-danger">No profile found</div>', 400

    from job_agent.orchestrator.engine import OrchestratorEngine

    engine = OrchestratorEngine(settings)
    task_id = task_runner.run(
        "Run Pipeline",
        engine.run_once,
        profile_path,
        platform,
        skip_activity_check=True,
    )

    return _status_snippet(task_id)


@bp.route("/discover-only", methods=["POST"])
def discover_only():
    """Start discovery-only (no applications) in a background thread."""
    settings = current_app.config["SETTINGS"]
    profile_name = request.form.get("profile")
    platform = request.form.get("platform") or None
    profile_path = _resolve_profile_path(profile_name)

    if not profile_path:
        return '<div class="alert alert-danger">No profile found</div>', 400

    from job_agent.orchestrator.engine import OrchestratorEngine

    engine = OrchestratorEngine(settings)
    task_id = task_runner.run(
        "Search Only",
        engine.run_once,
        profile_path,
        platform,
        skip_activity_check=True,
        discover_only=True,
    )

    return _status_snippet(task_id)


@bp.route("/cancel/<task_id>", methods=["POST"])
def cancel(task_id: str):
    """Cancel a running task."""
    if task_runner.cancel(task_id):
        return (
            '<div id="action-status">'
            '<div class="alert alert-warning">'
            '<i class="bi bi-x-circle"></i> Task cancelled.'
            "</div></div>"
        )
    return (
        '<div id="action-status">'
        '<div class="alert alert-danger">Task not found or already finished.</div>'
        "</div>"
    )


@bp.route("/test-login", methods=["POST"])
def test_login():
    """Test login for a platform in a background thread."""
    settings = current_app.config["SETTINGS"]
    platform_name = request.form.get("platform", "")

    if not platform_name:
        return '<span class="badge badge-red">No platform</span>'

    def _test(settings, plat_name):
        from job_agent.browser.manager import BrowserManager
        from job_agent.db.models import Platform
        from job_agent.db.repository import CredentialRepository
        from job_agent.db.session import get_session
        from job_agent.orchestrator.pipeline import get_platform_driver
        from job_agent.utils.crypto import decrypt

        session = get_session(settings)
        try:
            cred = CredentialRepository(session).get(Platform(plat_name))
            if not cred:
                return {"ok": False, "message": f"No credentials for {plat_name}"}

            with BrowserManager(settings) as browser:
                driver = get_platform_driver(plat_name, settings, browser)
                driver.login(cred.username, decrypt(cred.encrypted_password))
                driver.close()
            return {"ok": True, "message": f"{plat_name} login successful"}
        except Exception as e:
            return {"ok": False, "message": str(e)[:200]}
        finally:
            session.close()

    task_id = task_runner.run(
        f"Test Login ({platform_name})", _test, settings, platform_name
    )
    return _status_snippet(task_id)


@bp.route("/status/<task_id>")
def status(task_id: str):
    """Return an HTMX snippet with the current task status."""
    info = task_runner.get_status(task_id)
    if info is None:
        return '<div class="alert alert-danger">Task not found</div>', 404

    return _render_status(info)


def _status_snippet(task_id: str) -> str:
    """Return the initial polling snippet for a newly started task."""
    return (
        f'<div id="action-status" '
        f'hx-get="/actions/status/{escape(task_id)}" '
        f'hx-trigger="every 2s" '
        f'hx-swap="outerHTML">'
        f'<div class="alert alert-info" style="display:flex;align-items:center;gap:0.5rem;">'
        f'<span class="spinner"></span> Task started...'
        f"</div></div>"
    )


def _render_status(info: dict) -> str:
    """Render a status snippet based on task state."""
    task_id = info["task_id"]
    status = info["status"]

    if status == "running":
        progress = info.get("progress", {})
        phase = progress.get("phase", "")
        phase_text = f" &mdash; {escape(phase)}" if phase else ""
        cancel_btn = (
            f' <button class="btn btn-ghost btn-sm" '
            f'hx-post="/actions/cancel/{escape(task_id)}" '
            f'hx-target="#action-status" '
            f'hx-swap="outerHTML" '
            f'style="margin-left:auto;">'
            f'<i class="bi bi-x-circle"></i> Cancel'
            f"</button>"
        )
        return (
            f'<div id="action-status" '
            f'hx-get="/actions/status/{escape(task_id)}" '
            f'hx-trigger="every 2s" '
            f'hx-swap="outerHTML">'
            f'<div class="alert alert-info" style="display:flex;align-items:center;gap:0.5rem;">'
            f'<span class="spinner"></span> {escape(info["name"])} running{phase_text}...'
            f"{cancel_btn}"
            f"</div></div>"
        )
    elif status == "completed":
        result = info.get("result", {})
        details = (
            ", ".join(f"{k}: {v}" for k, v in result.items())
            if isinstance(result, dict)
            else str(result)
        )
        return (
            f'<div id="action-status">'
            f'<div class="alert alert-success">'
            f'<i class="bi bi-check-circle"></i> '
            f"{escape(info['name'])} completed &mdash; {escape(details)}"
            f"</div></div>"
        )
    elif status == "cancelled":
        return (
            f'<div id="action-status">'
            f'<div class="alert alert-warning">'
            f'<i class="bi bi-x-circle"></i> '
            f"{escape(info['name'])} cancelled."
            f"</div></div>"
        )
    else:
        error = info.get("error", "Unknown error")
        return (
            f'<div id="action-status">'
            f'<div class="alert alert-danger">'
            f'<i class="bi bi-exclamation-triangle"></i> '
            f"{escape(info['name'])} failed: {escape(str(error))}"
            f"</div></div>"
        )
