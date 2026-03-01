"""Outreach message listing with response tracking and email draft management."""

from __future__ import annotations

import json

from flask import Blueprint, render_template, current_app, request, redirect, url_for, flash

from job_agent.ai.client import AIClient
from job_agent.ai.cold_email import ColdEmailGenerator
from job_agent.db.session import get_session
from job_agent.db.repository import JobRepository, OutreachRepository
from job_agent.db.models import JobStatus, OutreachStatus

bp = Blueprint("outreach", __name__)


def _build_candidate_summary(profile: dict) -> str:
    """Build a candidate summary string from a profile dict."""
    parts: list[str] = []
    if name := profile.get("name"):
        parts.append(f"Target Role: {name}")
    search = profile.get("search", {})
    if exp := search.get("experience_level"):
        parts.append(f"Experience Level: {exp}")
    skills = profile.get("skills", {})
    if req := skills.get("required"):
        parts.append(f"Required Skills: {', '.join(req)}")
    if pref := skills.get("preferred"):
        parts.append(f"Preferred Skills: {', '.join(pref)}")
    return "\n".join(parts)


@bp.route("/")
def index():
    """Outreach message list with response tracking."""
    session = get_session(current_app.config["SETTINGS"])
    try:
        outreach_repo = OutreachRepository(session)
        job_repo = JobRepository(session)

        current_tab = request.args.get("tab", "all")

        all_messages = outreach_repo.list_all(limit=200)

        # Filter based on tab
        if current_tab == "emails":
            messages = [m for m in all_messages if m.message_type == "email"]
        elif current_tab == "connections":
            messages = [m for m in all_messages if m.message_type != "email"]
        else:
            messages = all_messages

        # Compute summary stats
        total = len(all_messages)
        sent = sum(1 for m in all_messages if m.status not in (OutreachStatus.PENDING, OutreachStatus.DRAFTED))
        drafted = sum(1 for m in all_messages if m.status == OutreachStatus.DRAFTED)
        accepted = sum(1 for m in all_messages if m.status == OutreachStatus.ACCEPTED)
        replied = sum(1 for m in all_messages if m.status == OutreachStatus.REPLIED)
        follow_ups = sum(
            1 for m in all_messages if m.status == OutreachStatus.FOLLOW_UP_SENT
        )
        failed = sum(1 for m in all_messages if m.status == OutreachStatus.FAILED)
        response_rate = (
            round((accepted + replied) / sent * 100, 1) if sent > 0 else 0.0
        )

        stats = {
            "total": total,
            "sent": sent,
            "drafted": drafted,
            "accepted": accepted,
            "replied": replied,
            "follow_ups": follow_ups,
            "failed": failed,
            "response_rate": response_rate,
        }

        # Get APPLIED jobs for the generate email form
        applied_jobs = job_repo.list_by_status(JobStatus.APPLIED, limit=200)

        return render_template(
            "outreach/index.html",
            messages=messages,
            stats=stats,
            current_tab=current_tab,
            applied_jobs=applied_jobs,
            OutreachStatus=OutreachStatus,
        )
    finally:
        session.close()


@bp.route("/generate-email/<int:job_id>", methods=["POST"])
def generate_email(job_id: int):
    """Generate a cold email draft for a job."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        job_repo = JobRepository(session)
        outreach_repo = OutreachRepository(session)

        job = job_repo.get_by_id(job_id)
        if not job:
            flash("Job not found.", "error")
            return redirect(url_for("outreach.index"))

        recipient_name = request.form.get("recipient_name", "").strip()
        recipient_title = request.form.get("recipient_title", "").strip()
        recipient_email = request.form.get("recipient_email", "").strip()

        if not recipient_name:
            flash("Recipient name is required.", "error")
            return redirect(url_for("outreach.index"))

        # Dedup check
        if outreach_repo.exists_email_for_job(job_id, recipient_name):
            flash(f"Email draft already exists for {recipient_name} on this job.", "warning")
            return redirect(url_for("outreach.index", tab="emails"))

        # Get matched skills from match result
        matched_skills: list[str] = []
        if job.match_result and job.match_result.matched_skills:
            try:
                matched_skills = json.loads(job.match_result.matched_skills)
            except (ValueError, TypeError):
                pass

        # Build candidate summary from available profiles
        from job_agent.config import load_profile
        from pathlib import Path

        candidate_summary = ""
        profiles_dir = Path("config/profiles")
        if profiles_dir.exists():
            for p in profiles_dir.glob("*.yaml"):
                if p.name != "example.yaml":
                    try:
                        profile = load_profile(str(p))
                        candidate_summary = _build_candidate_summary(profile)
                        break
                    except Exception:
                        pass

        # Generate email via AI
        ai_client = AIClient(settings)
        generator = ColdEmailGenerator(ai_client, settings)
        email_data = generator.generate(
            job_title=job.title,
            company=job.company,
            recipient_name=recipient_name,
            recipient_title=recipient_title,
            matched_skills=matched_skills,
            candidate_summary=candidate_summary,
        )

        # Store as OutreachMessage
        outreach_repo.create(
            platform=job.platform,
            recipient_name=recipient_name,
            recipient_title=recipient_title,
            recipient_company=job.company,
            recipient_profile_url=recipient_email,
            message_type="email",
            message_text=json.dumps(email_data),
            status=OutreachStatus.DRAFTED,
            related_job_id=job.id,
        )
        session.commit()

        flash(f"Email draft generated for {recipient_name}.", "success")
        return redirect(url_for("outreach.index", tab="emails"))

    except Exception as e:
        session.rollback()
        flash(f"Failed to generate email: {e}", "error")
        return redirect(url_for("outreach.index"))
    finally:
        session.close()


@bp.route("/mark-sent/<int:message_id>", methods=["POST"])
def mark_sent(message_id: int):
    """Mark a drafted email as sent."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        outreach_repo = OutreachRepository(session)
        msg = outreach_repo.mark_as_sent(message_id)
        if msg:
            session.commit()
            flash("Email marked as sent.", "success")
        else:
            flash("Message not found.", "error")
        return redirect(url_for("outreach.index", tab="emails"))
    except Exception as e:
        session.rollback()
        flash(f"Error: {e}", "error")
        return redirect(url_for("outreach.index"))
    finally:
        session.close()


@bp.route("/delete/<int:message_id>", methods=["POST"])
def delete_message(message_id: int):
    """Delete an outreach message draft."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        outreach_repo = OutreachRepository(session)
        if outreach_repo.delete(message_id):
            session.commit()
            flash("Draft deleted.", "success")
        else:
            flash("Message not found.", "error")
        return redirect(url_for("outreach.index", tab="emails"))
    except Exception as e:
        session.rollback()
        flash(f"Error: {e}", "error")
        return redirect(url_for("outreach.index"))
    finally:
        session.close()
