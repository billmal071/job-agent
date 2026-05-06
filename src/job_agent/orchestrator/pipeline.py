"""Discovery → Dedup → Match → Decide → Apply pipeline."""

from __future__ import annotations

from job_agent.ai.client import AIClient
from job_agent.ai.cover_letter import CoverLetterGenerator
from job_agent.ai.job_matcher import JobMatcher
from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.browser.manager import BrowserManager
from job_agent.config import Settings, load_profile
from job_agent.db.models import (
    ApplicationStatus,
    Job,
    JobStatus,
    Platform,
)
from job_agent.db.repository import (
    ApplicationRepository,
    CredentialRepository,
    JobRepository,
    MatchResultRepository,
)
from job_agent.db.session import get_session
from job_agent.orchestrator.pipeline_steps import (
    apply_to_job,
    build_candidate_summary,
    decide_job,
    generate_cold_email_draft,
    get_matched_skills_for_job,
    match_job,
)
from job_agent.platforms.base import JobPosting, PlatformDriver
from job_agent.platforms.linkedin.driver import LinkedInDriver
from job_agent.utils.crypto import decrypt
from job_agent.utils.logging import bind_contextvars, get_logger

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


def _login_driver(
    driver: PlatformDriver,
    platform_name: str,
    session,
    ai_client: AIClient,
    profile: dict,
) -> bool:
    """Login the driver using stored credentials. Returns False if no credentials found."""
    cred = CredentialRepository(session).get(Platform(platform_name))
    if not cred:
        log.warning("no_credentials", platform=platform_name)
        return False
    driver.login(cred.username, decrypt(cred.encrypted_password))
    if hasattr(driver, "set_ai_context"):
        driver.set_ai_context(ai_client, profile)
    return True


def _discover_postings(
    driver: PlatformDriver,
    search: dict,
    job_repo: JobRepository,
) -> list[tuple[JobPosting, bool]]:
    """Discover job postings for all keywords/locations. Returns list of (posting, needs_detail)."""
    results: list[tuple[JobPosting, bool]] = []
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
                    remote=search.get("remote_preference", "") == "remote_only",
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
                if job_repo.exists(posting.external_id, posting.platform):
                    continue
                results.append((posting, not posting.description))

    return results


def _process_approved_queue(
    *,
    approved_jobs: list[Job],
    settings: Settings,
    browser: BrowserManager,
    session,
    app_repo: ApplicationRepository,
    ai_client: AIClient,
    resume_tailor: ResumeTailor,
    cover_letter_gen: CoverLetterGenerator,
    candidate_summary: str,
    profile: dict,
    stats: dict,
) -> None:
    """Process all APPROVED jobs grouped by platform inside an existing browser session."""
    if not approved_jobs:
        return

    log.info("processing_approved_jobs", count=len(approved_jobs))

    by_platform: dict[str, list[Job]] = {}
    for job in approved_jobs:
        by_platform.setdefault(job.platform.value, []).append(job)

    for plat, jobs in by_platform.items():
        bind_contextvars(platform=plat)
        cred = CredentialRepository(session).get(Platform(plat))
        if not cred:
            log.warning("no_credentials_for_approved")
            continue

        try:
            driver = get_platform_driver(plat, settings, browser)
            driver.login(cred.username, decrypt(cred.encrypted_password))
            if hasattr(driver, "set_ai_context"):
                driver.set_ai_context(ai_client, profile)

            for job in jobs:
                bind_contextvars(job_id=job.id)
                if settings.agent.dry_run:
                    log.info("dry_run_approved", title=job.title)
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
                    matched_skills = get_matched_skills_for_job(job)
                    success = apply_to_job(
                        job=job,
                        posting=posting,
                        driver=driver,
                        resume_tailor=resume_tailor,
                        cover_letter_gen=cover_letter_gen,
                        app_repo=app_repo,
                        candidate_summary=candidate_summary,
                        matched_skills=matched_skills,
                    )
                    if success:
                        stats["applied"] += 1
                        log.info(
                            "approved_job_applied",
                            job_id=job.id,
                            title=job.title,
                            company=job.company,
                        )
                        generate_cold_email_draft(
                            job=job,
                            ai_client=ai_client,
                            settings=settings,
                            profile=profile,
                            session=session,
                        )
                    else:
                        log.warning(
                            "approved_job_apply_failed",
                            job_id=job.id,
                            title=job.title,
                            company=job.company,
                            platform=plat,
                        )
                except Exception as e:
                    log.error(
                        "approved_job_error",
                        job_id=job.id,
                        title=job.title,
                        company=job.company,
                        platform=plat,
                        error=str(e),
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
            log.error("approved_platform_error", platform=plat, error=str(e))


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
    candidate_summary = build_candidate_summary(profile)

    try:
        with BrowserManager(settings) as browser:
            for plat in platforms_to_run:
                bind_contextvars(platform=plat)
                driver = get_platform_driver(plat, settings, browser)

                if not _login_driver(driver, plat, session, ai_client, profile):
                    continue

                # Discover postings
                postings_with_flags = _discover_postings(driver, search, job_repo)

                for posting, needs_detail in postings_with_flags:
                    if needs_detail:
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
                    bind_contextvars(job_id=job.id)

                    # Match
                    score = match_job(
                        job=job,
                        posting=posting,
                        matcher=matcher,
                        match_repo=match_repo,
                        profile=profile,
                    )
                    stats["matched"] += 1

                    # Decide
                    decision = decide_job(job, score, settings)

                    if decision == "auto_apply":
                        if not settings.agent.dry_run:
                            try:
                                matched_skills = get_matched_skills_for_job(job)
                                success = apply_to_job(
                                    job=job,
                                    posting=posting,
                                    driver=driver,
                                    resume_tailor=resume_tailor,
                                    cover_letter_gen=cover_letter_gen,
                                    app_repo=app_repo,
                                    candidate_summary=candidate_summary,
                                    matched_skills=matched_skills,
                                )
                                if success:
                                    stats["applied"] += 1
                                    generate_cold_email_draft(
                                        job=job,
                                        ai_client=ai_client,
                                        settings=settings,
                                        profile=profile,
                                        session=session,
                                    )
                            except Exception as e:
                                log.error(
                                    "apply_error",
                                    job_id=job.id,
                                    title=job.title,
                                    company=job.company,
                                    platform=plat,
                                    error=str(e),
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
                    elif decision == "queue":
                        stats["queued"] += 1
                    else:
                        stats["skipped"] += 1

                    session.commit()

                driver.close()

            # Process approved jobs from the review queue
            approved_jobs = job_repo.list_by_status(JobStatus.APPROVED)
            _process_approved_queue(
                approved_jobs=approved_jobs,
                settings=settings,
                browser=browser,
                session=session,
                app_repo=app_repo,
                ai_client=ai_client,
                resume_tailor=resume_tailor,
                cover_letter_gen=cover_letter_gen,
                candidate_summary=candidate_summary,
                profile=profile,
                stats=stats,
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
    candidate_summary = build_candidate_summary(profile)

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
                bind_contextvars(platform=plat)
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
                        bind_contextvars(job_id=job.id)
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
                            matched_skills = get_matched_skills_for_job(job)
                            success = apply_to_job(
                                job=job,
                                posting=posting,
                                driver=driver,
                                resume_tailor=resume_tailor,
                                cover_letter_gen=cover_letter_gen,
                                app_repo=app_repo,
                                candidate_summary=candidate_summary,
                                matched_skills=matched_skills,
                            )
                            if success:
                                stats["applied"] += 1
                                log.info(
                                    "approved_job_applied",
                                    job_id=job.id,
                                    title=job.title,
                                    company=job.company,
                                )
                                generate_cold_email_draft(
                                    job=job,
                                    ai_client=ai_client,
                                    settings=settings,
                                    profile=profile,
                                    session=session,
                                )
                            else:
                                stats["failed"] += 1
                                log.warning(
                                    "approved_job_apply_failed",
                                    job_id=job.id,
                                    title=job.title,
                                    company=job.company,
                                    platform=plat,
                                )
                        except Exception as e:
                            log.error(
                                "approved_job_error",
                                job_id=job.id,
                                title=job.title,
                                company=job.company,
                                platform=plat,
                                error=str(e),
                            )
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
