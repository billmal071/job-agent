"""Apply to approved Indeed jobs by navigating to job pages and following external ATS links.

Uses Camoufox to bypass Cloudflare, navigates to Indeed job pages,
finds "Apply on company site" links, and applies on external ATS.
"""
import sys
import json
import time
sys.path.insert(0, "src")

from camoufox.sync_api import Camoufox
from job_agent.ai.client import AIClient
from job_agent.ai.cover_letter import CoverLetterGenerator
from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.ai.screening import ScreeningAnswerer
from job_agent.config import Settings, load_profile
from job_agent.db.models import Job, JobStatus, Platform
from job_agent.db.repository import ApplicationRepository, JobRepository
from job_agent.db.session import get_session
from job_agent.platforms.base import JobPosting
from job_agent.platforms.external_ats import ExternalATSApplicator
from job_agent.browser.humanizer import human_delay
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


def build_candidate_summary(profile: dict) -> str:
    parts = []
    if name := profile.get("name"):
        parts.append(f"Target Role: {name}")
    search = profile.get("search", {})
    if exp := search.get("experience_level"):
        parts.append(f"Experience Level: {exp}")
    if locs := search.get("locations"):
        parts.append(f"Locations: {', '.join(locs)}")
    skills = profile.get("skills", {})
    if req := skills.get("required"):
        parts.append(f"Required Skills: {', '.join(req)}")
    if pref := skills.get("preferred"):
        parts.append(f"Preferred Skills: {', '.join(pref)}")
    if salary := search.get("salary_minimum"):
        parts.append(f"Minimum Salary: ${salary:,}")
    return "\n".join(parts)


def dismiss_indeed_modals(page):
    """Dismiss sign-in modals, popups, and overlays on Indeed."""
    try:
        # Close sign-in modal
        close_btns = page.locator(
            'button[aria-label="Close"], '
            'button:has-text("Not now"), '
            'button:has-text("Skip"), '
            '[data-testid="modal-close"], '
            '.icl-Modal-close, '
            'button.icl-CloseButton'
        )
        if close_btns.count() > 0:
            close_btns.first.click(force=True)
            human_delay(500, 1000)
    except Exception:
        pass

    try:
        # Remove overlay via JS
        page.evaluate("""
            document.querySelectorAll('.icl-Modal, .gnav-Overlay, [class*="modal"]').forEach(e => e.remove());
            document.querySelectorAll('.popover, [role="dialog"]').forEach(e => e.remove());
            document.body.style.overflow = 'auto';
        """)
    except Exception:
        pass


def find_external_apply_url(page) -> str | None:
    """Find the external ATS apply URL on an Indeed job page."""
    # Strategy 1: Look for "Apply on company site" or external apply link
    selectors = [
        'a:has-text("Apply on company site")',
        'a:has-text("Apply now")',
        'button:has-text("Apply on")',
        'a.jobsearch-IndeedApplyButton-newDesign',
        'a[href*="applystart"]',
        'a[data-tn-element="apply-button"]',
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0:
                href = el.get_attribute("href") or ""
                if href:
                    return href
        except Exception:
            continue

    # Strategy 2: Find any external link in the apply area
    try:
        apply_section = page.locator(
            '#applyButtonLinkContainer, '
            '.jobsearch-ViewJobButtons-container, '
            '#jobsearch-ViewjobPaneWrapper'
        )
        if apply_section.count() > 0:
            links = apply_section.locator("a[href]").all()
            for link in links:
                href = link.get_attribute("href") or ""
                if href and "indeed.com" not in href:
                    return href
    except Exception:
        pass

    return None


def main():
    settings = Settings()
    profile = load_profile("config/profiles/williams.yaml")
    ai_client = AIClient(settings)
    resume_tailor = ResumeTailor(ai_client, settings)
    cover_letter_gen = CoverLetterGenerator(ai_client, settings)
    candidate_summary = build_candidate_summary(profile)
    salary = str(profile.get("search", {}).get("salary_minimum", ""))
    answerer = ScreeningAnswerer(ai_client, candidate_summary, salary)

    session = get_session(settings)
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)

    approved = job_repo.list_by_status(JobStatus.APPROVED)
    indeed_jobs = [j for j in approved if j.platform == Platform.INDEED]
    linkedin_jobs = [j for j in approved if j.platform == Platform.LINKEDIN]

    print(f"Approved: {len(approved)} total")
    print(f"  Indeed: {len(indeed_jobs)} (will process)")
    print(f"  LinkedIn: {len(linkedin_jobs)} (skipping for now)")

    if not indeed_jobs:
        print("No Indeed jobs to apply to.")
        return

    stats = {"applied": 0, "failed": 0, "skipped": 0}

    with Camoufox(headless=False, humanize=True) as browser:
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()

        for i, job in enumerate(indeed_jobs, 1):
            print(f"\n[{i}/{len(indeed_jobs)}] {job.title} @ {job.company}")

            # Extract jk from URL for viewjob navigation
            jk = ""
            url = job.url or ""
            if "jk=" in url:
                import re
                m = re.search(r"jk=([a-f0-9]+)", url)
                if m:
                    jk = m.group(1)

            if not jk:
                print(f"  SKIP: No job key found in URL")
                stats["skipped"] += 1
                continue

            try:
                # Build resume and cover letter
                posting = JobPosting(
                    external_id=job.external_id,
                    platform=job.platform,
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    description=job.description or "",
                    url=job.url,
                    easy_apply=False,
                    remote=job.remote,
                    salary=job.salary,
                )

                matched_skills = []
                if job.match_result and job.match_result.matched_skills:
                    try:
                        matched_skills = json.loads(job.match_result.matched_skills)
                    except (ValueError, TypeError):
                        pass

                resume_path = resume_tailor.tailor_and_save(posting, matched_skills)
                try:
                    cl_path = cover_letter_gen.generate_and_save(
                        posting, candidate_summary, matched_skills
                    )
                except Exception as e:
                    log.warning("cover_letter_failed", error=str(e))
                    cl_path = ""

                # Navigate to Indeed job page
                viewjob_url = f"https://www.indeed.com/viewjob?jk={jk}"
                page.goto(viewjob_url, timeout=30000)
                human_delay(3000, 5000)

                # Dismiss any modals/overlays
                dismiss_indeed_modals(page)
                human_delay(1000, 2000)

                # Check if Cloudflare blocked us
                if "just a moment" in page.title().lower():
                    print(f"  SKIP: Cloudflare blocked")
                    stats["skipped"] += 1
                    continue

                # Find external apply URL
                ext_url = find_external_apply_url(page)
                if ext_url:
                    print(f"  Found apply link: {ext_url[:80]}")
                    # Navigate to external ATS
                    if ext_url.startswith("/"):
                        ext_url = f"https://www.indeed.com{ext_url}"

                    pages_before = len(ctx.pages)
                    page.goto(ext_url, timeout=30000)
                    human_delay(3000, 5000)

                    # Check if opened new tab
                    target_page = page
                    if len(ctx.pages) > pages_before:
                        target_page = ctx.pages[-1]

                    current = target_page.url
                    print(f"  On: {current[:80]}")

                    if "indeed.com" not in current:
                        # On external ATS — apply!
                        ats = ExternalATSApplicator(target_page, answerer)
                        success = ats.apply(posting, resume_path, cl_path)
                        if target_page != page:
                            target_page.close()
                        if success:
                            job.status = JobStatus.APPLIED
                            app_repo.create(job_id=job.id, resume_path=resume_path, cover_letter_path=cl_path)
                            stats["applied"] += 1
                            print(f"  SUCCESS!")
                        else:
                            job.status = JobStatus.APPLY_FAILED
                            stats["failed"] += 1
                            print(f"  FAILED: Could not complete")
                    else:
                        # Still on Indeed — try clicking the link directly
                        print(f"  SKIP: Redirect stayed on Indeed")
                        stats["skipped"] += 1
                else:
                    # No external link — try clicking apply button
                    apply_btn = page.locator(
                        '#indeedApplyButton, '
                        'button[id*="apply"], '
                        'button:has-text("Apply now"), '
                        'button:has-text("Apply")'
                    ).first
                    if apply_btn.count() > 0:
                        apply_btn.click(force=True)
                        human_delay(3000, 5000)
                        if "indeed.com" not in page.url:
                            ats = ExternalATSApplicator(page, answerer)
                            success = ats.apply(posting, resume_path, cl_path)
                            if success:
                                job.status = JobStatus.APPLIED
                                app_repo.create(job_id=job.id, resume_path=resume_path, cover_letter_path=cl_path)
                                stats["applied"] += 1
                                print(f"  SUCCESS!")
                            else:
                                job.status = JobStatus.APPLY_FAILED
                                stats["failed"] += 1
                                print(f"  FAILED: Could not complete")
                        else:
                            print(f"  SKIP: No external redirect after click")
                            stats["skipped"] += 1
                    else:
                        print(f"  SKIP: No apply button found")
                        stats["skipped"] += 1

            except Exception as e:
                log.error("apply_error", job_id=job.id, error=str(e))
                job.status = JobStatus.APPLY_FAILED
                stats["failed"] += 1
                print(f"  ERROR: {str(e)[:100]}")

            session.commit()
            human_delay(2000, 4000)

        page.close()
        ctx.close()

    session.close()
    print(f"\n{'='*50}")
    print(f"Results: {stats}")


if __name__ == "__main__":
    main()
