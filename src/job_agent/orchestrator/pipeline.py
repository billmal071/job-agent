"""Discovery → Dedup → Match → Decide → Apply pipeline."""

from __future__ import annotations

from job_agent.ai.client import AIClient
from job_agent.ai.job_matcher import JobMatcher
from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.browser.manager import BrowserManager
from job_agent.config import Settings, load_profile
from job_agent.db.models import JobStatus, Platform
from job_agent.db.repository import (
    ApplicationRepository,
    JobRepository,
    MatchResultRepository,
)
from job_agent.db.session import get_session
from job_agent.platforms.base import PlatformDriver
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

    drivers = {
        "linkedin": lambda: LinkedInDriver(settings, browser_manager),
        "indeed": lambda: IndeedDriver(settings, browser_manager),
        "glassdoor": lambda: GlassdoorDriver(settings, browser_manager),
    }
    factory = drivers.get(platform_name)
    if not factory:
        raise ValueError(f"Unsupported platform: {platform_name}")
    return factory()


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
                raise RuntimeError(f"No credentials for {platform_name}. Run: job-agent add-credential {platform_name}")

            driver.login(cred.username, decrypt(cred.encrypted_password))

            # Search
            postings = driver.search_jobs(query=query, location=location, limit=limit)

            # Store in DB (dedup)
            stored: list[Job] = []
            for posting in postings:
                if not job_repo.exists(posting.external_id, posting.platform):
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
                    )
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
        for p in ["linkedin", "indeed", "glassdoor"]:
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

                # Discover
                for kw in search.get("keywords", []):
                    for loc in search.get("locations", [""]):
                        postings = driver.search_jobs(
                            query=kw,
                            location=loc,
                            remote=search.get("remote_preference", "") == "remote_only",
                            experience_level=search.get("experience_level", ""),
                            limit=25,
                        )

                        for posting in postings:
                            # Dedup
                            if job_repo.exists(posting.external_id, posting.platform):
                                continue

                            # Get full details
                            try:
                                detailed = driver.get_job_details(posting.url)
                                posting.description = detailed.description
                            except Exception:
                                pass

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
                                if not settings.agent.dry_run and posting.easy_apply:
                                    # Tailor resume and apply
                                    try:
                                        resume_path = resume_tailor.tailor_and_save(
                                            posting, score.matched_skills
                                        )
                                        success = driver.apply(posting, resume_path)
                                        if success:
                                            job.status = JobStatus.APPLIED
                                            app_repo.create(
                                                job_id=job.id,
                                                resume_path=resume_path,
                                            )
                                            stats["applied"] += 1
                                        else:
                                            job.status = JobStatus.APPLY_FAILED
                                    except Exception as e:
                                        log.error("apply_error", job_id=job.id, error=str(e))
                                        job.status = JobStatus.APPLY_FAILED
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

        log.info("pipeline_complete", **stats)
        return stats

    except Exception as e:
        session.rollback()
        log.error("pipeline_failed", error=str(e))
        raise
    finally:
        session.close()
