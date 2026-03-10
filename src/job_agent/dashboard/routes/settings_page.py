"""Settings page routes for credentials and thresholds."""

from __future__ import annotations

from pathlib import Path

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

_ENV_PATH = Path(".env")
_ENV_EXAMPLE_PATH = Path(".env.example")

_AI_PROVIDERS = ["gemini", "groq", "openrouter", "ollama", "anthropic"]

_PROVIDER_KEY_FIELDS = {
    "gemini": "gemini_api_key",
    "groq": "groq_api_key",
    "openrouter": "openrouter_api_key",
    "anthropic": "anthropic_api_key",
}


def _write_env_var(key: str, value: str) -> None:
    """Update or append a key=value in the project .env file."""
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text().splitlines(keepends=True)
    elif _ENV_EXAMPLE_PATH.exists():
        lines = _ENV_EXAMPLE_PATH.read_text().splitlines(keepends=True)
    else:
        lines = []

    upper_key = key.upper()
    found = False
    new_lines = []
    for line in lines:
        stripped = line.lstrip("# ").strip()
        if stripped.startswith(upper_key + "=") or stripped.startswith(upper_key + " ="):
            new_lines.append(f"{upper_key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines.append("\n")
        new_lines.append(f"{upper_key}={value}\n")

    _ENV_PATH.write_text("".join(new_lines))


def _mask_key(key: str) -> str:
    """Mask an API key, showing only the last 4 characters."""
    if not key:
        return ""
    if len(key) <= 4:
        return key
    return "\u2022" * 6 + key[-4:]


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

        ai_config = {
            "provider": settings.ai_provider,
            "gemini_key": _mask_key(settings.gemini_api_key),
            "groq_key": _mask_key(settings.groq_api_key),
            "openrouter_key": _mask_key(settings.openrouter_api_key),
            "anthropic_key": _mask_key(settings.anthropic_api_key),
            "providers": _AI_PROVIDERS,
        }

        email_config = {
            "smtp_user": settings.smtp_user,
            "smtp_user_masked": _mask_key(settings.smtp_user) if settings.smtp_user else "",
            "smtp_password_set": bool(settings.smtp_password),
            "notification_email": settings.notification_email,
        }

        return render_template(
            "settings/index.html",
            credentials=credentials,
            thresholds=thresholds,
            ai_config=ai_config,
            email_config=email_config,
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
        _write_env_var("JOB_AGENT_MATCHING__AUTO_APPLY_THRESHOLD", str(auto_apply))
    if review is not None:
        settings.matching.review_threshold = review
        _write_env_var("JOB_AGENT_MATCHING__REVIEW_THRESHOLD", str(review))

    flash("Thresholds updated.", "success")
    return redirect(url_for("settings_page.index"))


@bp.route("/ai-provider", methods=["POST"])
def update_ai_provider():
    """Update AI provider and API keys."""
    settings = current_app.config["SETTINGS"]

    provider = request.form.get("ai_provider", "").strip().lower()
    if provider not in _AI_PROVIDERS:
        flash(f"Invalid AI provider: {provider}", "danger")
        return redirect(url_for("settings_page.index"))

    # Collect API keys from form
    key_map = {
        "gemini_api_key": request.form.get("gemini_api_key", "").strip(),
        "groq_api_key": request.form.get("groq_api_key", "").strip(),
        "openrouter_api_key": request.form.get("openrouter_api_key", "").strip(),
        "anthropic_api_key": request.form.get("anthropic_api_key", "").strip(),
    }

    # Write non-empty keys to .env and update in-memory settings
    for field, value in key_map.items():
        if value:
            env_key = f"JOB_AGENT_{field.upper()}"
            _write_env_var(env_key, value)
            setattr(settings, field, value)

    # Validate that the selected provider has a key (ollama doesn't need one)
    if provider != "ollama":
        key_field = _PROVIDER_KEY_FIELDS.get(provider)
        current_key = getattr(settings, key_field, "") if key_field else ""
        if not current_key:
            flash(
                f"Warning: No API key configured for {provider}. "
                "The provider has been set, but it won't work without a key.",
                "warning",
            )

    # Write provider selection to .env and update in-memory
    _write_env_var("JOB_AGENT_AI_PROVIDER", provider)
    settings.ai_provider = provider

    flash(f"AI provider set to {provider}.", "success")
    return redirect(url_for("settings_page.index"))


@bp.route("/email", methods=["POST"])
def update_email():
    """Update SMTP / email settings."""
    settings = current_app.config["SETTINGS"]

    smtp_user = request.form.get("smtp_user", "").strip()
    smtp_password = request.form.get("smtp_password", "").strip()
    notification_email = request.form.get("notification_email", "").strip()

    if smtp_user:
        _write_env_var("JOB_AGENT_SMTP_USER", smtp_user)
        settings.smtp_user = smtp_user
    if smtp_password:
        _write_env_var("JOB_AGENT_SMTP_PASSWORD", smtp_password)
        settings.smtp_password = smtp_password
    if notification_email:
        _write_env_var("JOB_AGENT_NOTIFICATION_EMAIL", notification_email)
        settings.notification_email = notification_email

    flash("Email settings updated.", "success")
    return redirect(url_for("settings_page.index"))
