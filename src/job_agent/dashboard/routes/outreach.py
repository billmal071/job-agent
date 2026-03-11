"""Outreach message listing with response tracking and email draft management."""

from __future__ import annotations

import json
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from flask import (
    Blueprint,
    render_template,
    current_app,
    request,
    redirect,
    url_for,
    flash,
)

from job_agent.ai.client import AIClient
from job_agent.ai.cold_email import ColdEmailGenerator
from job_agent.db.session import get_session
from job_agent.db.repository import JobRepository, OutreachRepository
from job_agent.db.models import JobStatus, OutreachStatus, Platform

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
        sent = sum(
            1
            for m in all_messages
            if m.status not in (OutreachStatus.PENDING, OutreachStatus.DRAFTED)
        )
        drafted = sum(1 for m in all_messages if m.status == OutreachStatus.DRAFTED)
        accepted = sum(1 for m in all_messages if m.status == OutreachStatus.ACCEPTED)
        replied = sum(1 for m in all_messages if m.status == OutreachStatus.REPLIED)
        follow_ups = sum(
            1 for m in all_messages if m.status == OutreachStatus.FOLLOW_UP_SENT
        )
        failed = sum(1 for m in all_messages if m.status == OutreachStatus.FAILED)
        response_rate = round((accepted + replied) / sent * 100, 1) if sent > 0 else 0.0

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
            flash(
                f"Email draft already exists for {recipient_name} on this job.",
                "warning",
            )
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


@bp.route("/send-email/<int:message_id>", methods=["POST"])
def send_email(message_id: int):
    """Send an email draft via SMTP."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        # Validate SMTP config
        if not settings.smtp_user or not settings.smtp_password:
            flash(
                "SMTP not configured. Go to Settings > Email to set up Gmail.", "error"
            )
            return redirect(url_for("outreach.index", tab="emails"))

        outreach_repo = OutreachRepository(session)
        msg = outreach_repo.get_by_id(message_id)
        if not msg:
            flash("Message not found.", "error")
            return redirect(url_for("outreach.index", tab="emails"))

        if msg.status != OutreachStatus.DRAFTED:
            flash("Only drafted emails can be sent.", "warning")
            return redirect(url_for("outreach.index", tab="emails"))

        # Get recipient email from form or stored profile URL
        recipient_email = request.form.get("recipient_email", "").strip()
        if not recipient_email:
            recipient_email = msg.recipient_profile_url or ""
        if not recipient_email or "@" not in recipient_email:
            flash("Recipient email address is required.", "error")
            return redirect(url_for("outreach.index", tab="emails"))

        # Parse email data
        try:
            email_data = json.loads(msg.message_text)
            subject = email_data.get("subject", f"Re: {msg.recipient_company}")
            body = email_data.get("body", msg.message_text)
        except (json.JSONDecodeError, TypeError):
            subject = f"Re: {msg.recipient_company}"
            body = msg.message_text

        # Send via SMTP
        email_msg = MIMEText(body)
        email_msg["Subject"] = subject
        email_msg["From"] = settings.smtp_user
        email_msg["To"] = recipient_email

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(email_msg)

        # Mark as sent
        outreach_repo.mark_as_sent(message_id)
        # Store recipient email if not already stored
        if msg.recipient_profile_url != recipient_email:
            msg.recipient_profile_url = recipient_email
        session.commit()

        flash(f"Email sent to {recipient_email}.", "success")
        return redirect(url_for("outreach.index", tab="emails"))
    except smtplib.SMTPAuthenticationError:
        session.rollback()
        flash(
            "SMTP authentication failed. Check your Gmail address and App Password in Settings.",
            "error",
        )
        return redirect(url_for("outreach.index", tab="emails"))
    except Exception as e:
        session.rollback()
        flash(f"Failed to send email: {e}", "error")
        return redirect(url_for("outreach.index", tab="emails"))
    finally:
        session.close()


@bp.route("/quick-apply", methods=["POST"])
def quick_apply():
    """Generate a tailored application email and send it with CV attached."""
    settings = current_app.config["SETTINGS"]
    session = get_session(settings)
    try:
        # Validate SMTP
        if not settings.smtp_user or not settings.smtp_password:
            flash(
                "SMTP not configured. Go to Settings > Email to set up Gmail.", "error"
            )
            return redirect(url_for("outreach.index"))

        raw_posting = request.form.get("raw_posting", "").strip()
        company = request.form.get("company", "").strip()
        job_title = request.form.get("job_title", "").strip()
        job_description = request.form.get("job_description", "").strip()
        recipient_email = request.form.get("recipient_email", "").strip()
        recipient_name = (
            request.form.get("recipient_name", "").strip() or "Hiring Manager"
        )

        # If raw posting provided, use AI to extract structured fields
        if raw_posting and (not company or not job_title or not recipient_email):
            ai_client = AIClient(settings)
            extract_prompt = (
                "Extract the following from this job posting. Return ONLY valid JSON, no markdown:\n"
                '{"company": "...", "job_title": "...", "recipient_email": "...", '
                '"recipient_name": "...", "description": "..."}\n'
                "If a field is not found, use an empty string.\n\n"
                f"Job posting:\n{raw_posting}"
            )
            try:
                raw_result = ai_client.complete(
                    prompt=extract_prompt,
                    system="You extract structured data from job postings. Return only valid JSON.",
                    max_tokens=512,
                    temperature=0.1,
                )
                extracted = json.loads(raw_result.strip())
                if not company:
                    company = extracted.get("company", "")
                if not job_title:
                    job_title = extracted.get("job_title", "")
                if not recipient_email:
                    recipient_email = extracted.get("recipient_email", "")
                if recipient_name == "Hiring Manager" and extracted.get(
                    "recipient_name"
                ):
                    recipient_name = extracted["recipient_name"]
                if not job_description:
                    job_description = extracted.get("description", raw_posting)
            except (json.JSONDecodeError, Exception):
                # Fallback: use raw posting as description
                if not job_description:
                    job_description = raw_posting

        if not company or not job_title or not recipient_email:
            flash(
                "Could not extract company, job title, or email. Please fill in the override fields.",
                "error",
            )
            return redirect(url_for("outreach.index"))

        # Build candidate summary from profile
        from job_agent.config import load_profile

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

        # Extract skills from job description as matched_skills
        matched_skills: list[str] = []
        if job_description:
            known_skills = [
                "Python",
                "Java",
                "TypeScript",
                "JavaScript",
                "React",
                "Node.js",
                "Spring Boot",
                "NestJS",
                "Docker",
                "Kubernetes",
                "AWS",
                "SQL",
                "PostgreSQL",
                "MongoDB",
                "REST",
                "APIs",
                "Terraform",
                "Next.js",
                "Express",
                "Rust",
                "Go",
                "DigitalOcean",
                "Redis",
                "GraphQL",
            ]
            desc_lower = job_description.lower()
            matched_skills = [s for s in known_skills if s.lower() in desc_lower]

        # Tailor resume for this job
        from job_agent.ai.resume_tailor import ResumeTailor
        from job_agent.platforms.base import JobPosting

        ai_client = AIClient(settings)
        resume_tailor = ResumeTailor(ai_client, settings)
        posting = JobPosting(
            external_id=f"quick-{company.lower().replace(' ', '-')}",
            platform=Platform.LINKEDIN,
            title=job_title,
            company=company,
            location="",
            description=job_description or raw_posting or "",
            url="",
        )
        try:
            tailored_resume_path = resume_tailor.tailor_and_save(
                posting, matched_skills
            )
        except Exception:
            tailored_resume_path = str(Path(settings.resume.master_resume))

        # Generate email via AI
        generator = ColdEmailGenerator(ai_client, settings)
        email_data = generator.generate(
            job_title=job_title,
            company=company,
            recipient_name=recipient_name,
            recipient_title="",
            matched_skills=matched_skills,
            candidate_summary=candidate_summary,
        )

        subject = email_data.get("subject", f"Application: {job_title} - {company}")
        body = email_data.get("body", "")

        # Build email with tailored CV attachment
        msg = MIMEMultipart()
        msg["From"] = settings.smtp_user
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        resume_file = Path(tailored_resume_path)
        if resume_file.exists():
            with open(resume_file, "rb") as f:
                part = MIMEBase("application", "pdf")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=f"CV_{resume_file.stem}.pdf",
                )
                msg.attach(part)

        # Send
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

        # Record in outreach table
        outreach_repo = OutreachRepository(session)
        outreach_repo.create(
            platform=Platform.LINKEDIN,
            recipient_name=recipient_name,
            recipient_title=job_title,
            recipient_company=company,
            recipient_profile_url=recipient_email,
            message_type="email",
            message_text=json.dumps(email_data),
            status=OutreachStatus.SENT,
            related_job_id=None,
        )
        session.commit()

        flash(
            f"Application sent to {recipient_email} for {job_title} at {company}.",
            "success",
        )
        return redirect(url_for("outreach.index", tab="emails"))
    except smtplib.SMTPAuthenticationError:
        session.rollback()
        flash(
            "SMTP authentication failed. Check your Gmail App Password in Settings.",
            "error",
        )
        return redirect(url_for("outreach.index"))
    except Exception as e:
        session.rollback()
        flash(f"Failed to send application: {e}", "error")
        return redirect(url_for("outreach.index"))
    finally:
        session.close()
