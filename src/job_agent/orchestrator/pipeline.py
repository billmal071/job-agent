"""Discovery → Dedup → Match → Decide → Apply pipeline."""

from __future__ import annotations

import json

from job_agent.ai.client import AIClient
from job_agent.ai.cold_email import ColdEmailGenerator
from job_agent.ai.cover_letter import CoverLetterGenerator
from job_agent.ai.job_matcher import JobMatcher
from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.browser.manager import BrowserManager
from job_agent.config import Settings, load_profile
from job_agent.db.models import (
    ApplicationStatus,
    Job,
    JobStatus,
    OutreachStatus,
    Platform,
)
from job_agent.db.repository import (
    ApplicationRepository,
    JobRepository,
    MatchResultRepository,
    OutreachRepository,
)
from job_agent.db.session import get_session
from job_agent.platforms.base import JobPosting, PlatformDriver
from job_agent.platforms.linkedin.driver import LinkedInDriver
from job_agent.utils.crypto import decrypt
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def get_platform_driver(
    platform_name: str, settings: Settings, browser_manager: BrowserManager
) -> PlatformDriver:
    """Factory for platform drivers."""
    from job_agent.platforms.indeed.driver import IndeedDriver
    from job_agent.platforms.glassdoor.driver import GlassdoorDriver
    from job_agent.platforms.ziprecruiter.driver import ZipRecruiterDriver
    from job_agent.platforms.dice.driver import DiceDriver
    from job_agent.platforms.wellfound.driver import WellfoundDriver

    drivers = {
        "linkedin": lambda: LinkedInDriver(settings, browser_manager),
        "indeed": lambda: IndeedDriver(settings, browser_manager),
        "glassdoor": lambda: GlassdoorDriver(settings, browser_manager),
        "ziprecruiter": lambda: ZipRecruiterDriver(settings, browser_manager),
        "dice": lambda: DiceDriver(settings, browser_manager),
        "wellfound": lambda: WellfoundDriver(settings, browser_manager),
    }
    factory = drivers.get(platform_name)
    if not factory:
        raise ValueError(f"Unsupported platform: {platform_name}")
    return factory()


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


def _generate_cold_email_draft(
    job,
    ai_client: AIClient,
    settings: Settings,
    profile: dict,
    session,
) -> None:
    """Generate a cold email draft for a successfully applied job. Non-fatal on failure."""
    try:
        outreach_repo = OutreachRepository(session)

        # Build candidate summary from profile
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
        candidate_summary = "\n".join(parts)

        # Get matched skills
        matched_skills: list[str] = []
        if job.match_result and job.match_result.matched_skills:
            try:
                matched_skills = json.loads(job.match_result.matched_skills)
            except (ValueError, TypeError):
                pass

        # Default recipient — use "Hiring Manager" as placeholder
        recipient_name = "Hiring Manager"
        recipient_title = "Recruiter"

        # Skip if draft already exists
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
        log.warning("cold_email_draft_failed", job_id=job.id, error=str(e))


def discover_jobs(
    settings: Settings,
    platform_name: str,
    query: str,
    location: str = "",
    limit: int = 25,
) -> list[Job]:
    """Discover and store jobs from a platform."""
    session = get_session(settings)
    job_repo = JobRepository(session)

    try:
        with BrowserManager(settings) as browser:
            driver = get_platform_driver(platform_name, settings, browser)

            # Login
            from job_agent.db.repository import CredentialRepository

            cred = CredentialRepository(session).get(Platform(platform_name))
            if not cred:
                raise RuntimeError(
                    f"No credentials for {platform_name}. Run: job-agent add-credential {platform_name}"
                )

            driver.login(cred.username, decrypt(cred.encrypted_password))

            # Search
            postings = driver.search_jobs(query=query, location=location, limit=limit)

            # Store in DB (dedup)
            stored: list[Job] = []
            for posting in postings:
                if not job_repo.exists(posting.external_id, posting.platform):
                    # Check cross-platform duplicate
                    duplicate_of = job_repo.find_cross_platform_duplicate(
                        posting.title, posting.company, posting.platform
                    )
                    job = job_repo.create(
                        external_id=posting.external_id,
                        platform=posting.platform,
                        title=posting.title,
                        company=posting.company,
                        location=posting.location,
                        description=posting.description,
                        url=posting.url,
                        salary=posting.salary,
                        easy_apply=posting.easy_apply,
                        remote=posting.remote,
                        duplicate_of_id=duplicate_of.id if duplicate_of else None,
                    )
                    if duplicate_of:
                        job.status = JobStatus.REJECTED
                        log.info(
                            "job_duplicate_skipped",
                            title=job.title,
                            company=job.company,
                            original_platform=duplicate_of.platform.value,
                        )
                    else:
                        stored.append(job)
                        log.info("job_discovered", title=job.title, company=job.company)

            session.commit()
            driver.close()

        log.info("discovery_complete", total=len(postings), new=len(stored))
        return stored

    except Exception as e:
        session.rollback()
        log.error("discovery_failed", error=str(e))
        raise
    finally:
        session.close()


def run_pipeline(
    settings: Settings,
    profile_path: str,
    platform_name: str | None = None,
) -> dict[str, int]:
    """Run the full discover → match → decide → apply pipeline."""
    profile = load_profile(profile_path)
    search = profile.get("search", {})
    stats = {"discovered": 0, "matched": 0, "applied": 0, "queued": 0, "skipped": 0}

    platforms_to_run = []
    if platform_name:
        platforms_to_run = [platform_name]
    else:
        for p in [
            "linkedin",
            "indeed",
            "glassdoor",
            "ziprecruiter",
            "dice",
            "wellfound",
        ]:
            cfg = getattr(settings.platforms, p)
            if cfg.enabled:
                platforms_to_run.append(p)

    session = get_session(settings)
    job_repo = JobRepository(session)
    match_repo = MatchResultRepository(session)
    app_repo = ApplicationRepository(session)
    ai_client = AIClient(settings)
    matcher = JobMatcher(ai_client)
    resume_tailor = ResumeTailor(ai_client, settings)
    cover_letter_gen = CoverLetterGenerator(ai_client, settings)
    candidate_summary = _build_candidate_summary(profile)

    try:
        with BrowserManager(settings) as browser:
            for plat in platforms_to_run:
                driver = get_platform_driver(plat, settings, browser)

                # Login
                from job_agent.db.repository import CredentialRepository

                cred = CredentialRepository(session).get(Platform(plat))
                if not cred:
                    log.warning("no_credentials", platform=plat)
                    continue

                driver.login(cred.username, decrypt(cred.encrypted_password))

                if hasattr(driver, "set_ai_context"):
                    driver.set_ai_context(ai_client, profile)

                # Discover
                consecutive_search_failures = 0
                for kw in search.get("keywords", []):
                    if consecutive_search_failures >= 3:
                        log.error("too_many_search_failures_stopping_discovery")
                        break
                    for loc in search.get("locations", [""]):
                        try:
                            postings = driver.search_jobs(
                                query=kw,
                                location=loc,
                                remote=search.get("remote_preference", "")
                                == "remote_only",
                                experience_level=search.get("experience_level", ""),
                                limit=25,
                            )
                            consecutive_search_failures = 0
                        except Exception as e:
                            consecutive_search_failures += 1
                            log.warning(
                                "search_failed",
                                query=kw,
                                location=loc,
                                error=str(e)[:200],
                            )
                            continue

                        for posting in postings:
                            # Dedup
                            if job_repo.exists(posting.external_id, posting.platform):
                                continue

                            # Get full details if not already fetched
                            if not posting.description:
                                try:
                                    detailed = driver.get_job_details(posting.url)
                                    posting.description = detailed.description
                                except Exception as e:
                                    log.warning(
                                        "detail_fetch_failed",
                                        url=posting.url,
                                        error=str(e),
                                    )

                            job = job_repo.create(
                                external_id=posting.external_id,
                                platform=posting.platform,
                                title=posting.title,
                                company=posting.company,
                                location=posting.location,
                                description=posting.description,
                                url=posting.url,
                                salary=posting.salary,
                                easy_apply=posting.easy_apply,
                                remote=posting.remote,
                                profile_name=profile.get("name", ""),
                            )
                            stats["discovered"] += 1

                            # Match
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
                            stats["matched"] += 1

                            # Decide
                            if score.score >= settings.matching.auto_apply_threshold:
                                job.status = JobStatus.AUTO_APPROVED
                                if not settings.agent.dry_run:
                                    # Tailor resume, generate cover letter, and apply
                                    try:
                                        resume_path = resume_tailor.tailor_and_save(
                                            posting, score.matched_skills
                                        )
                                        try:
                                            cl_path = (
                                                cover_letter_gen.generate_and_save(
                                                    posting,
                                                    candidate_summary,
                                                    score.matched_skills,
                                                )
                                            )
                                        except Exception as e:
                                            log.warning(
                                                "cover_letter_failed",
                                                job_id=job.id,
                                                error=str(e),
                                            )
                                            cl_path = ""
                                        success = driver.apply(
                                            posting,
                                            resume_path,
                                            cover_letter_path=cl_path,
                                        )
                                        if success:
                                            job.status = JobStatus.APPLIED
                                            app_repo.create(
                                                job_id=job.id,
                                                resume_path=resume_path,
                                                cover_letter_path=cl_path,
                                                status=ApplicationStatus.SUBMITTED,
                                            )
                                            stats["applied"] += 1
                                            _generate_cold_email_draft(
                                                job,
                                                ai_client,
                                                settings,
                                                profile,
                                                session,
                                            )
                                        else:
                                            job.status = JobStatus.APPLY_FAILED
                                            app_repo.create(
                                                job_id=job.id,
                                                resume_path=resume_path,
                                                cover_letter_path=cl_path,
                                                status=ApplicationStatus.FAILED,
                                                error_message="Application submission failed",
                                            )
                                    except Exception as e:
                                        log.error(
                                            "apply_error", job_id=job.id, error=str(e)
                                        )
                                        job.status = JobStatus.APPLY_FAILED
                                        app_repo.create(
                                            job_id=job.id,
                                            resume_path="",
                                            cover_letter_path="",
                                            status=ApplicationStatus.FAILED,
                                            error_message=str(e)[:500],
                                        )
                                else:
                                    stats["applied"] += 1  # dry run counts
                            elif score.score >= settings.matching.review_threshold:
                                job.status = JobStatus.QUEUED
                                stats["queued"] += 1
                            else:
                                job.status = JobStatus.SKIPPED
                                stats["skipped"] += 1

                            session.commit()

                driver.close()

            # Process approved jobs from the review queue
            approved_jobs = job_repo.list_by_status(JobStatus.APPROVED)
            if approved_jobs:
                log.info("processing_approved_jobs", count=len(approved_jobs))

                # Group by platform
                by_platform: dict[str, list] = {}
                for job in approved_jobs:
                    plat_name = job.platform.value
                    by_platform.setdefault(plat_name, []).append(job)

                for plat, jobs in by_platform.items():
                    from job_agent.db.repository import CredentialRepository

                    cred = CredentialRepository(session).get(Platform(plat))
                    if not cred:
                        log.warning("no_credentials_for_approved", platform=plat)
                        continue

                    try:
                        driver = get_platform_driver(plat, settings, browser)
                        driver.login(cred.username, decrypt(cred.encrypted_password))

                        if hasattr(driver, "set_ai_context"):
                            driver.set_ai_context(ai_client, profile)

                        for job in jobs:
                            if settings.agent.dry_run:
                                log.info(
                                    "dry_run_approved", job_id=job.id, title=job.title
                                )
                                job.status = JobStatus.APPLIED
                                app_repo.create(job_id=job.id, resume_path="")
                                stats["applied"] += 1
                                session.commit()
                                continue

                            try:
                                posting = JobPosting(
                                    external_id=job.external_id,
                                    platform=job.platform,
                                    title=job.title,
                                    company=job.company,
                                    location=job.location,
                                    description=job.description or "",
                                    url=job.url,
                                    easy_apply=True,  # User explicitly approved
                                    remote=job.remote,
                                    salary=job.salary,
                                )

                                # Tailor resume
                                matched_skills: list[str] = []
                                if job.match_result and job.match_result.matched_skills:
                                    try:
                                        matched_skills = json.loads(
                                            job.match_result.matched_skills
                                        )
                                    except (ValueError, TypeError):
                                        matched_skills = []
                                resume_path = resume_tailor.tailor_and_save(
                                    posting, matched_skills
                                )
                                try:
                                    cl_path = cover_letter_gen.generate_and_save(
                                        posting, candidate_summary, matched_skills
                                    )
                                except Exception as e:
                                    log.warning(
                                        "cover_letter_failed",
                                        job_id=job.id,
                                        error=str(e),
                                    )
                                    cl_path = ""

                                success = driver.apply(
                                    posting, resume_path, cover_letter_path=cl_path
                                )
                                if success:
                                    job.status = JobStatus.APPLIED
                                    app_repo.create(
                                        job_id=job.id,
                                        resume_path=resume_path,
                                        cover_letter_path=cl_path,
                                        status=ApplicationStatus.SUBMITTED,
                                    )
                                    stats["applied"] += 1
                                    log.info(
                                        "approved_job_applied",
                                        job_id=job.id,
                                        title=job.title,
                                    )
                                    _generate_cold_email_draft(
                                        job, ai_client, settings, profile, session
                                    )
                                else:
                                    job.status = JobStatus.APPLY_FAILED
                                    app_repo.create(
                                        job_id=job.id,
                                        resume_path=resume_path,
                                        cover_letter_path=cl_path,
                                        status=ApplicationStatus.FAILED,
                                        error_message="Application submission failed",
                                    )
                                    log.warning(
                                        "approved_job_apply_failed", job_id=job.id
                                    )
                            except Exception as e:
                                log.error(
                                    "approved_job_error", job_id=job.id, error=str(e)
                                )
                                job.status = JobStatus.APPLY_FAILED
                                app_repo.create(
                                    job_id=job.id,
                                    resume_path="",
                                    cover_letter_path="",
                                    status=ApplicationStatus.FAILED,
                                    error_message=str(e)[:500],
                                )

                            session.commit()

                        driver.close()
                    except Exception as e:
                        log.error(
                            "approved_platform_error", platform=plat, error=str(e)
                        )

        log.info("pipeline_complete", **stats)
        return stats

    except Exception as e:
        session.rollback()
        log.error("pipeline_failed", error=str(e))
        raise
    finally:
        session.close()


def apply_approved(settings: Settings, profile_path: str = "") -> dict[str, int]:
    """Apply to all APPROVED jobs from the review queue (skips discovery)."""
    stats = {"applied": 0, "failed": 0, "skipped": 0}

    session = get_session(settings)
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    ai_client = AIClient(settings)
    resume_tailor = ResumeTailor(ai_client, settings)
    cover_letter_gen = CoverLetterGenerator(ai_client, settings)
    profile = load_profile(profile_path) if profile_path else {}
    candidate_summary = _build_candidate_summary(profile)

    try:
        approved_jobs = job_repo.list_by_status(JobStatus.APPROVED)
        if not approved_jobs:
            log.info("no_approved_jobs")
            return stats

        log.info("applying_approved_jobs", count=len(approved_jobs))

        # Group by platform
        by_platform: dict[str, list] = {}
        for job in approved_jobs:
            by_platform.setdefault(job.platform.value, []).append(job)

        with BrowserManager(settings) as browser:
            for plat, jobs in by_platform.items():
                from job_agent.db.repository import CredentialRepository

                cred = CredentialRepository(session).get(Platform(plat))
                if not cred:
                    log.warning("no_credentials_for_approved", platform=plat)
                    continue

                try:
                    driver = get_platform_driver(plat, settings, browser)
                    driver.login(cred.username, decrypt(cred.encrypted_password))

                    if profile and hasattr(driver, "set_ai_context"):
                        driver.set_ai_context(ai_client, profile)

                    for job in jobs:
                        try:
                            posting = JobPosting(
                                external_id=job.external_id,
                                platform=job.platform,
                                title=job.title,
                                company=job.company,
                                location=job.location,
                                description=job.description or "",
                                url=job.url,
                                easy_apply=True,  # User explicitly approved
                                remote=job.remote,
                                salary=job.salary,
                            )

                            matched_skills: list[str] = []
                            if job.match_result and job.match_result.matched_skills:
                                try:
                                    matched_skills = json.loads(
                                        job.match_result.matched_skills
                                    )
                                except (ValueError, TypeError):
                                    matched_skills = []

                            resume_path = resume_tailor.tailor_and_save(
                                posting, matched_skills
                            )
                            try:
                                cl_path = cover_letter_gen.generate_and_save(
                                    posting, candidate_summary, matched_skills
                                )
                            except Exception as e:
                                log.warning(
                                    "cover_letter_failed", job_id=job.id, error=str(e)
                                )
                                cl_path = ""

                            success = driver.apply(
                                posting, resume_path, cover_letter_path=cl_path
                            )
                            if success:
                                job.status = JobStatus.APPLIED
                                app_repo.create(
                                    job_id=job.id,
                                    resume_path=resume_path,
                                    cover_letter_path=cl_path,
                                    status=ApplicationStatus.SUBMITTED,
                                )
                                stats["applied"] += 1
                                log.info(
                                    "approved_job_applied",
                                    job_id=job.id,
                                    title=job.title,
                                )
                                _generate_cold_email_draft(
                                    job, ai_client, settings, profile, session
                                )
                            else:
                                job.status = JobStatus.APPLY_FAILED
                                stats["failed"] += 1
                                log.warning("approved_job_apply_failed", job_id=job.id)
                        except Exception as e:
                            log.error("approved_job_error", job_id=job.id, error=str(e))
                            job.status = JobStatus.APPLY_FAILED
                            stats["failed"] += 1

                        session.commit()

                    driver.close()
                except Exception as e:
                    log.error("approved_platform_error", platform=plat, error=str(e))

        log.info("apply_approved_complete", **stats)
        return stats

    except Exception as e:
        session.rollback()
        log.error("apply_approved_failed", error=str(e))
        raise
    finally:
        session.close()
