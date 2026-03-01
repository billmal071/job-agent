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
        f.name
        for f in PROFILES_DIR.glob("*.yaml")
        if f.name != "example.yaml"
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

    from job_agent.orchestrator.pipeline import run_pipeline as _run_pipeline

    task_id = task_runner.run(
        "Run Pipeline", _run_pipeline, settings, profile_path, platform
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
        f'</div></div>'
    )


def _render_status(info: dict) -> str:
    """Render a status snippet based on task state."""
    task_id = info["task_id"]
    status = info["status"]

    if status == "running":
        return (
            f'<div id="action-status" '
            f'hx-get="/actions/status/{escape(task_id)}" '
            f'hx-trigger="every 2s" '
            f'hx-swap="outerHTML">'
            f'<div class="alert alert-info" style="display:flex;align-items:center;gap:0.5rem;">'
            f'<span class="spinner"></span> {escape(info["name"])} running...'
            f'</div></div>'
        )
    elif status == "completed":
        result = info.get("result", {})
        details = ", ".join(f"{k}: {v}" for k, v in result.items()) if isinstance(result, dict) else str(result)
        return (
            f'<div id="action-status">'
            f'<div class="alert alert-success">'
            f'{escape(info["name"])} completed &mdash; {escape(details)}'
            f'</div></div>'
        )
    else:
        error = info.get("error", "Unknown error")
        return (
            f'<div id="action-status">'
            f'<div class="alert alert-danger">'
            f'{escape(info["name"])} failed: {escape(str(error))}'
            f'</div></div>'
        )
