"""Extracted pipeline step functions — each handles one phase of the pipeline."""

from __future__ import annotations

import json

from job_agent.ai.cold_email import ColdEmailGenerator
from job_agent.ai.client import AIClient
from job_agent.ai.cover_letter import CoverLetterGenerator
from job_agent.ai.job_matcher import JobMatcher
from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.config import Settings
from job_agent.db.models import (
    ApplicationStatus,
    Job,
    JobStatus,
    OutreachStatus,
)
from job_agent.db.repository import (
    ApplicationRepository,
    MatchResultRepository,
    OutreachRepository,
)
from job_agent.platforms.base import JobPosting, PlatformDriver
from job_agent.utils.json_helpers import parse_json_list
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def match_job(
    *,
    job: Job,
    posting: JobPosting,
    matcher: JobMatcher,
    match_repo: MatchResultRepository,
    profile: dict,
) -> object:
    """Run AI matching on a single job. Updates job status to MATCHED and stores result."""
    score = matcher.match(posting, profile)
    match_repo.create(
        job_id=job.id,
        score=score.score,
        reasoning=score.reasoning,
        matched_skills=score.matched_skills,
        missing_skills=score.missing_skills,
        role_fit=score.role_fit,
        red_flags=score.red_flags,
    )
    job.status = JobStatus.MATCHED
    log.info("job_matched", job_id=job.id, score=score.score, title=job.title)
    return score


def decide_job(job: Job, score, settings: Settings) -> str:
    """Decide what to do with a matched job based on thresholds.

    Returns: "auto_apply", "queue", or "skip".
    """
    if score.score >= settings.matching.auto_apply_threshold:
        job.status = JobStatus.AUTO_APPROVED
        log.info("job_auto_approved", job_id=job.id, score=score.score)
        return "auto_apply"
    elif score.score >= settings.matching.review_threshold:
        job.status = JobStatus.QUEUED
        log.info("job_queued", job_id=job.id, score=score.score)
        return "queue"
    else:
        job.status = JobStatus.SKIPPED
        log.info("job_skipped", job_id=job.id, score=score.score)
        return "skip"


def apply_to_job(
    *,
    job: Job,
    posting: JobPosting,
    driver: PlatformDriver,
    resume_tailor: ResumeTailor,
    cover_letter_gen: CoverLetterGenerator,
    app_repo: ApplicationRepository,
    candidate_summary: str,
    matched_skills: list[str],
) -> bool:
    """Tailor resume, generate cover letter, and apply. Returns True on success."""
    resume_path = resume_tailor.tailor_and_save(posting, matched_skills)

    cl_path = ""
    try:
        cl_path = cover_letter_gen.generate_and_save(
            posting, candidate_summary, matched_skills
        )
    except Exception as e:
        log.warning(
            "cover_letter_generation_failed",
            job_id=job.id,
            company=job.company,
            error=str(e),
        )

    success = driver.apply(posting, resume_path, cover_letter_path=cl_path)

    if success:
        job.status = JobStatus.APPLIED
        app_repo.create(
            job_id=job.id,
            resume_path=resume_path,
            cover_letter_path=cl_path,
            status=ApplicationStatus.SUBMITTED,
        )
        log.info("job_applied", job_id=job.id, title=job.title, company=job.company)
    else:
        job.status = JobStatus.APPLY_FAILED
        app_repo.create(
            job_id=job.id,
            resume_path=resume_path,
            cover_letter_path=cl_path,
            status=ApplicationStatus.FAILED,
            error_message="Application submission returned failure",
        )
        log.warning("job_apply_failed", job_id=job.id, title=job.title)

    return success


def generate_cold_email_draft(
    *,
    job: Job,
    ai_client: AIClient,
    settings: Settings,
    profile: dict,
    session,
) -> None:
    """Generate a cold email draft for a successfully applied job. Non-fatal on failure."""
    try:
        outreach_repo = OutreachRepository(session)
        candidate_summary = build_candidate_summary(profile)

        matched_skills = parse_json_list(
            job.match_result.matched_skills if job.match_result else None
        )

        recipient_name = "Hiring Manager"
        recipient_title = "Recruiter"

        if outreach_repo.exists_email_for_job(job.id, recipient_name):
            return

        generator = ColdEmailGenerator(ai_client, settings)
        email_data = generator.generate(
            job_title=job.title,
            company=job.company,
            recipient_name=recipient_name,
            recipient_title=recipient_title,
            matched_skills=matched_skills,
            candidate_summary=candidate_summary,
        )

        outreach_repo.create(
            platform=job.platform,
            recipient_name=recipient_name,
            recipient_title=recipient_title,
            recipient_company=job.company,
            recipient_profile_url="",
            message_type="email",
            message_text=json.dumps(email_data),
            status=OutreachStatus.DRAFTED,
            related_job_id=job.id,
        )
        log.info("cold_email_draft_generated", job_id=job.id, company=job.company)
    except Exception as e:
        log.warning(
            "cold_email_draft_failed",
            job_id=job.id,
            company=job.company,
            error=str(e),
        )


def build_candidate_summary(profile: dict) -> str:
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


def get_matched_skills_for_job(job: Job) -> list[str]:
    """Extract matched skills list from a job's match result."""
    if not job.match_result or not job.match_result.matched_skills:
        return []
    return parse_json_list(job.match_result.matched_skills)
