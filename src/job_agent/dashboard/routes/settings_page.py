"""Settings page routes for credentials, thresholds, and profile generation."""

from __future__ import annotations

import traceback
from pathlib import Path

from flask import (
    Blueprint,
    render_template,
    request,
    current_app,
    redirect,
    url_for,
    flash,
    jsonify,
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

        # List existing profiles
        profiles_dir = Path("config/profiles")
        profiles = []
        if profiles_dir.exists():
            for p in sorted(profiles_dir.glob("*.yaml")):
                profiles.append(p.stem)

        return render_template(
            "settings/index.html",
            credentials=credentials,
            thresholds=thresholds,
            ai_config=ai_config,
            email_config=email_config,
            profiles=profiles,
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


def _extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file using pymupdf."""
    import fitz  # pymupdf

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text_parts = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts)


def _extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file."""
    import zipfile
    import io
    import xml.etree.ElementTree as ET

    zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    xml_content = zf.read("word/document.xml")
    tree = ET.fromstring(xml_content)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for p in tree.iter(f"{{{ns['w']}}}p"):
        texts = [t.text for t in p.iter(f"{{{ns['w']}}}t") if t.text]
        if texts:
            paragraphs.append("".join(texts))
    return "\n".join(paragraphs)


@bp.route("/generate-profile", methods=["POST"])
def generate_profile():
    """Generate a YAML profile from an uploaded CV/resume."""
    settings = current_app.config["SETTINGS"]

    uploaded = request.files.get("cv_file")
    profile_name = request.form.get("profile_name", "").strip() or "generated"

    if not uploaded or not uploaded.filename:
        flash("Please upload a CV file (PDF or DOCX).", "danger")
        return redirect(url_for("settings_page.index"))

    filename = uploaded.filename.lower()
    file_bytes = uploaded.read()

    # Extract text
    try:
        if filename.endswith(".pdf"):
            cv_text = _extract_text_from_pdf(file_bytes)
        elif filename.endswith(".docx"):
            cv_text = _extract_text_from_docx(file_bytes)
        else:
            flash("Unsupported file format. Please upload a PDF or DOCX.", "danger")
            return redirect(url_for("settings_page.index"))
    except Exception as e:
        flash(f"Failed to read file: {e}", "danger")
        return redirect(url_for("settings_page.index"))

    if not cv_text.strip():
        flash("Could not extract text from the uploaded file.", "danger")
        return redirect(url_for("settings_page.index"))

    # Generate profile via AI
    try:
        from job_agent.ai.client import AIClient
        from job_agent.ai.prompts import CV_TO_PROFILE_TEMPLATE

        ai = AIClient(settings)
        prompt = CV_TO_PROFILE_TEMPLATE.render(cv_text=cv_text[:8000])

        yaml_output = ai.complete(
            prompt=prompt,
            system="You are a career analyst. Output only valid YAML, nothing else.",
            max_tokens=2048,
            temperature=0.3,
        )

        # Strip any code fences the model might add
        yaml_output = yaml_output.strip()
        if yaml_output.startswith("```"):
            yaml_output = "\n".join(yaml_output.split("\n")[1:])
        if yaml_output.endswith("```"):
            yaml_output = "\n".join(yaml_output.split("\n")[:-1])
        yaml_output = yaml_output.strip()

        # Validate it's parseable YAML
        import yaml

        parsed = yaml.safe_load(yaml_output)
        if not isinstance(parsed, dict) or "name" not in parsed:
            flash("AI generated invalid profile. Please try again.", "danger")
            return redirect(url_for("settings_page.index"))

        # Save to config/profiles/
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "-"
            for c in profile_name.lower()
        )
        profile_path = Path("config/profiles") / f"{safe_name}.yaml"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(yaml_output)

        # Also save the uploaded CV as master resume
        resume_dir = Path("config/resumes")
        resume_dir.mkdir(parents=True, exist_ok=True)
        ext = ".pdf" if filename.endswith(".pdf") else ".docx"
        resume_path = resume_dir / f"master{ext}"
        resume_path.write_bytes(file_bytes)

        flash(
            f"Profile generated and saved to {profile_path}. "
            f"Resume saved to {resume_path}.",
            "success",
        )
    except Exception as e:
        traceback.print_exc()
        flash(f"AI generation failed: {e}", "danger")

    return redirect(url_for("settings_page.index"))
