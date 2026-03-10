"""Discover jobs on Glassdoor, screen them, and apply to approved ones.

Step 1: Load saved session
Step 2: Search for jobs using profile keywords
Step 3: Screen and score jobs via AI
Step 4: Apply to jobs scoring above threshold
"""
import sys
import time
sys.path.insert(0, "src")

from pathlib import Path
from camoufox.sync_api import Camoufox
from job_agent.ai.client import AIClient
from job_agent.ai.cover_letter import CoverLetterGenerator
from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.ai.screening import ScreeningAnswerer
from job_agent.config import Settings, load_profile
from job_agent.db.models import JobStatus, Platform
from job_agent.db.repository import ApplicationRepository, JobRepository
from job_agent.db.session import get_session
from job_agent.platforms.base import JobPosting
from job_agent.platforms.external_ats import ExternalATSApplicator
from job_agent.platforms.glassdoor.discovery import GlassdoorDiscovery
from job_agent.browser.humanizer import human_delay
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)

STATE_FILE = Path("~/.job-agent/browser_state/glassdoor_camoufox.json").expanduser()


def build_candidate_summary(profile: dict) -> str:
    parts = []
    personal = profile.get("personal", {})
    search = profile.get("search", {})
    skills = profile.get("skills", {})
    if full_name := personal.get("full_name"):
        parts.append(f"Full Name: {full_name}")
    if email := personal.get("email"):
        parts.append(f"Email: {email}")
    if phone := personal.get("phone"):
        parts.append(f"Phone: {phone}")
    if location := personal.get("location"):
        parts.append(f"Location: {location}")
    if linkedin := personal.get("linkedin"):
        parts.append(f"LinkedIn: {linkedin}")
    if github := personal.get("github"):
        parts.append(f"GitHub: {github}")
    if company := personal.get("current_company"):
        parts.append(f"Current Company: {company}")
    if name := profile.get("name"):
        parts.append(f"Target Role: {name}")
    if exp := search.get("experience_level"):
        parts.append(f"Experience Level: {exp}")
    if locs := search.get("locations"):
        parts.append(f"Locations: {', '.join(locs)}")
    if req := skills.get("required"):
        parts.append(f"Required Skills: {', '.join(req)}")
    if pref := skills.get("preferred"):
        parts.append(f"Preferred Skills: {', '.join(pref)}")
    if salary := search.get("salary_minimum"):
        parts.append(f"Minimum Salary: ${salary:,}")
    return "\n".join(parts)


def load_glassdoor_session(browser):
    """Load Glassdoor session from saved state."""
    if not STATE_FILE.exists():
        print("ERROR: No saved session. Run scripts/glassdoor_login_only.py first.")
        sys.exit(1)

    print(f"Loading session from {STATE_FILE}")
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        storage_state=str(STATE_FILE),
    )
    page = ctx.new_page()

    # Verify session works
    page.goto("https://www.glassdoor.com/Job/jobs.htm?sc.keyword=software+engineer", timeout=60000, wait_until="commit")
    time.sleep(5)
    title = page.title().lower()

    if "just a moment" in title:
        print("Waiting for Cloudflare...")
        for _ in range(12):
            time.sleep(5)
            if "just a moment" not in page.title().lower():
                break

    title = page.title().lower()
    if "just a moment" in title or "security" in title:
        print("ERROR: Blocked by Cloudflare. Try again later.")
        sys.exit(1)

    print(f"Session loaded OK: {page.title()}")
    return ctx, page


def discover_jobs(page, profile):
    """Search Glassdoor for jobs matching profile keywords."""
    rate_limiter = RateLimiter(requests_per_minute=10, failure_threshold=5, cooldown_seconds=60)
    discovery = GlassdoorDiscovery(page, rate_limiter)

    keywords = profile.get("search", {}).get("keywords", [])
    locations = profile.get("search", {}).get("locations", ["Remote"])

    all_jobs = []
    seen_ids = set()

    for keyword in keywords[:5]:  # Limit to first 5 keywords to avoid rate limits
        for location in locations[:2]:  # First 2 locations
            print(f"  Searching: '{keyword}' in '{location}'...")
            try:
                jobs = discovery.search(query=keyword, location=location, limit=10)
                for job in jobs:
                    if job.external_id not in seen_ids:
                        seen_ids.add(job.external_id)
                        all_jobs.append(job)
                print(f"    Found {len(jobs)} jobs ({len(all_jobs)} unique total)")
            except Exception as e:
                print(f"    Search failed: {str(e)[:80]}")
            human_delay(2000, 4000)

    return all_jobs


def screen_job(ai_client, job, profile):
    """Quick AI screen to check if job is a good match."""
    from job_agent.ai.job_matcher import JobMatcher
    matcher = JobMatcher(ai_client)
    result = matcher.match(job, profile)
    return result


def apply_to_job(page, ctx, job, resume_path, cl_path, answerer):
    """Navigate to job and apply via Glassdoor."""
    # Go to the job page
    page.goto(job.url, timeout=60000, wait_until="commit")
    human_delay(3000, 5000)

    # Handle Cloudflare
    if "just a moment" in page.title().lower():
        print("    Waiting for Cloudflare...")
        for _ in range(12):
            time.sleep(5)
            if "just a moment" not in page.title().lower():
                break
        if "just a moment" in page.title().lower():
            return "skip", "Cloudflare"

    # Find Apply button
    apply_btn = page.locator(
        'button:has-text("Apply on employer site"), '
        'a:has-text("Apply on employer site"), '
        'button:has-text("Easy Apply"), '
        '[data-test="applyButton"], '
        'button:has-text("Apply"), '
        'a:has-text("Apply")'
    ).first
    if apply_btn.count() == 0:
        return "skip", "No apply button"

    btn_text = apply_btn.inner_text().strip()
    apply_href = apply_btn.get_attribute("href") or ""
    print(f"    Button: '{btn_text}' href={apply_href[:80] if apply_href else 'none'}")

    # Handle "Apply on employer site" — redirects externally
    if "employer site" in btn_text.lower():
        # Click and wait for popup or navigation
        pages_before = len(ctx.pages)
        try:
            with page.expect_popup(timeout=15000) as popup_info:
                apply_btn.click(force=True)
            target_page = popup_info.value
        except Exception:
            # No popup — check if new tab appeared or page redirected
            human_delay(3000, 5000)
            if len(ctx.pages) > pages_before:
                target_page = ctx.pages[-1]
            elif "glassdoor.com" not in page.url:
                target_page = page
            else:
                # Try direct href navigation
                if apply_href:
                    target_page = ctx.new_page()
                    href = apply_href if apply_href.startswith("http") else f"https://www.glassdoor.com{apply_href}"
                    try:
                        target_page.goto(href, timeout=45000, wait_until="domcontentloaded")
                    except Exception:
                        pass
                    human_delay(3000, 5000)
                else:
                    return "skip", "No redirect from employer site button"

        current = target_page.url
        print(f"    Landed on: {current[:80]}")

        # Wait through Cloudflare
        if "just a moment" in target_page.title().lower():
            for _ in range(12):
                time.sleep(5)
                if "just a moment" not in target_page.title().lower():
                    break
            current = target_page.url

        if "glassdoor.com" not in current:
            ats = ExternalATSApplicator(target_page, answerer)
            result = ats.apply(job, resume_path, cl_path)
            if target_page != page:
                target_page.close()
            return ("success", "External ATS") if result else ("fail", "External ATS failed")
        if target_page != page:
            target_page.close()
        return "skip", f"Still on Glassdoor: {current[:60]}"

    # Handle "Easy Apply" — opens a modal on Glassdoor
    elif "easy apply" in btn_text.lower():
        apply_btn.click(force=True)
        human_delay(3000, 5000)

        # Look for the Easy Apply modal/dialog
        modal = page.locator(
            '[data-test="applyModal"], '
            '[class*="applyModal"], '
            '[role="dialog"], '
            '.modal-content'
        ).first
        if modal.count() == 0:
            return "skip", "Easy Apply modal not found"

        # Upload resume in modal
        file_input = modal.locator('input[type="file"]').first
        if file_input.count() > 0 and resume_path:
            from pathlib import Path as P
            if P(resume_path).exists():
                try:
                    file_input.set_input_files(resume_path)
                    human_delay(1000, 2000)
                except Exception:
                    pass

        # Fill fields in modal using answerer
        if answerer:
            from job_agent.ai.screening import FormField
            inputs = modal.locator('input[type="text"], input[type="email"], input[type="tel"], textarea, select').all()
            for inp in inputs:
                try:
                    current_val = inp.input_value() if inp.evaluate("el => el.tagName") != "SELECT" else ""
                    if current_val and current_val.strip():
                        continue
                    label = inp.get_attribute("aria-label") or inp.get_attribute("placeholder") or ""
                    if not label:
                        # Try associated label
                        inp_id = inp.get_attribute("id") or ""
                        if inp_id:
                            lbl = page.locator(f'label[for="{inp_id}"]').first
                            if lbl.count() > 0:
                                label = lbl.inner_text().strip()
                    if not label:
                        continue
                    tag = inp.evaluate("el => el.tagName.toLowerCase()")
                    ft = "select" if tag == "select" else "textarea" if tag == "textarea" else "text"
                    field = FormField(label=label, field_type=ft, selector="")
                    answer = answerer.answer_field(field)
                    if tag == "select":
                        try:
                            inp.select_option(label=answer.answer)
                        except Exception:
                            pass
                    else:
                        inp.fill(answer.answer)
                    human_delay(200, 500)
                except Exception:
                    continue

        # Click Submit/Continue in modal
        submit = modal.locator(
            'button:has-text("Submit"), '
            'button:has-text("Apply"), '
            'button:has-text("Continue"), '
            'button[type="submit"]'
        ).first
        if submit.count() > 0:
            submit.click(force=True)
            human_delay(3000, 5000)

            body = page.locator("body").inner_text().lower()
            if any(p in body for p in ("application submitted", "thank you", "successfully applied")):
                return "success", "Easy Apply"

        return "fail", "Easy Apply incomplete"

    # Generic fallback
    else:
        apply_btn.click(force=True)
        human_delay(5000, 8000)
        if "glassdoor.com" not in page.url:
            ats = ExternalATSApplicator(page, answerer)
            result = ats.apply(job, resume_path, cl_path)
            return ("success", "External ATS") if result else ("fail", "External ATS failed")
        return "skip", "No redirect"


def main():
    settings = Settings()
    profile = load_profile("config/profiles/williams.yaml")
    ai_client = AIClient(settings)
    resume_tailor = ResumeTailor(ai_client, settings)
    cover_letter_gen = CoverLetterGenerator(ai_client, settings)
    candidate_summary = build_candidate_summary(profile)
    salary = str(profile.get("search", {}).get("salary_minimum", ""))
    answerer = ScreeningAnswerer(ai_client, candidate_summary, salary)

    db_session = get_session(settings)
    job_repo = JobRepository(db_session)
    app_repo = ApplicationRepository(db_session)

    stats = {"discovered": 0, "approved": 0, "applied": 0, "failed": 0, "skipped": 0}

    with Camoufox(headless=False, humanize=True) as browser:
        ctx, page = load_glassdoor_session(browser)

        # Step 1: Discover jobs
        print("\n=== DISCOVERING JOBS ===")
        discovered_jobs = discover_jobs(page, profile)
        stats["discovered"] = len(discovered_jobs)
        print(f"\nDiscovered {len(discovered_jobs)} unique jobs")

        # Step 2: Save to DB and screen
        print("\n=== SCREENING JOBS ===")
        approved_jobs = []
        for job in discovered_jobs:
            # Check if already in DB
            existing = job_repo.get_by_external_id(job.external_id, Platform.GLASSDOOR)
            if existing:
                if existing.status == JobStatus.APPROVED:
                    approved_jobs.append((existing, job))
                continue

            # Save to DB
            db_job = job_repo.create(
                external_id=job.external_id,
                platform=Platform.GLASSDOOR,
                title=job.title,
                company=job.company,
                location=job.location,
                url=job.url,
                salary=job.salary,
                remote=job.remote,
                easy_apply=job.easy_apply,
            )

            # Quick title-based filter for obviously irrelevant jobs
            title_lower = job.title.lower()
            skip_keywords = [
                "clearance", "polygraph", "ts/sci", "secret",
                "c++", "c#", ".net", "blazor", "ruby", "scala",
                "ios", "android", "mobile", "data scientist",
                "machine learning", "ml engineer", "firmware",
                "embedded", "erp", "blockchain", "salesforce",
                "junior", "intern", "unpaid", "volunteer",
            ]
            if any(kw in title_lower for kw in skip_keywords):
                print(f"  SKIPPED (title filter): {job.title} @ {job.company}")
                db_session.commit()
                human_delay(500, 1000)
                continue

            # Get details for better matching
            try:
                discovery = GlassdoorDiscovery(page, RateLimiter(10, 5, 60))
                details = discovery.get_details(job.url)
                if details.description:
                    db_job.description = details.description
                    job.description = details.description
            except Exception as e:
                print(f"  Could not get details for {job.title}: {str(e)[:50]}")

            # Auto-approve if it has a description (we can screen later)
            if job.description:
                try:
                    match = screen_job(ai_client, job, profile)
                    if match and match.score >= 0.80:
                        db_job.status = JobStatus.APPROVED
                        approved_jobs.append((db_job, job))
                        stats["approved"] += 1
                        print(f"  APPROVED ({match.score:.0%}): {job.title} @ {job.company}")
                    else:
                        score = match.score if match else 0
                        print(f"  REJECTED ({score:.0%}): {job.title} @ {job.company}")
                except Exception as e:
                    # Auto-approve on screening failure
                    db_job.status = JobStatus.APPROVED
                    approved_jobs.append((db_job, job))
                    stats["approved"] += 1
                    print(f"  APPROVED (default): {job.title} @ {job.company}")
            else:
                db_job.status = JobStatus.APPROVED
                approved_jobs.append((db_job, job))
                stats["approved"] += 1
                print(f"  APPROVED (no desc): {job.title} @ {job.company}")

            db_session.commit()
            human_delay(1000, 2000)

        print(f"\n{len(approved_jobs)} jobs approved for application")

        # Step 3: Apply to approved jobs
        if approved_jobs:
            print("\n=== APPLYING TO JOBS ===")
            for i, (db_job, posting) in enumerate(approved_jobs, 1):
                print(f"\n[{i}/{len(approved_jobs)}] {posting.title} @ {posting.company}")

                try:
                    # Generate resume and cover letter
                    resume_dir = Path("~/.job-agent/resumes").expanduser()
                    cl_dir = Path("~/.job-agent/cover_letters").expanduser()
                    safe_name = f"{posting.company}_{posting.external_id}".replace(" ", "_").replace("/", "_")

                    existing_resume = list(resume_dir.glob(f"*{posting.external_id}*"))
                    existing_cl = list(cl_dir.glob(f"*{posting.external_id}*"))

                    if existing_resume:
                        resume_path = str(existing_resume[0])
                        print(f"  Reusing resume: {existing_resume[0].name}")
                    else:
                        resume_path = resume_tailor.tailor_and_save(posting, [])

                    if existing_cl:
                        cl_path = str(existing_cl[0])
                    else:
                        try:
                            cl_path = cover_letter_gen.generate_and_save(
                                posting, candidate_summary, []
                            )
                        except Exception as e:
                            log.warning("cover_letter_failed", error=str(e))
                            cl_path = ""

                    result, detail = apply_to_job(page, ctx, posting, resume_path, cl_path, answerer)

                    if result == "success":
                        db_job.status = JobStatus.APPLIED
                        app_repo.create(job_id=db_job.id, resume_path=resume_path, cover_letter_path=cl_path)
                        stats["applied"] += 1
                        print(f"  SUCCESS: {detail}")
                    elif result == "fail":
                        stats["failed"] += 1
                        print(f"  FAILED: {detail}")
                    else:
                        stats["skipped"] += 1
                        print(f"  SKIPPED: {detail}")

                except Exception as e:
                    err = str(e)
                    log.error("apply_error", job_id=db_job.id, error=err)
                    stats["failed"] += 1
                    print(f"  ERROR: {err[:100]}")

                db_session.commit()
                # Longer delay to avoid Groq rate limits
                human_delay(5000, 8000)

        page.close()
        ctx.close()

    db_session.close()
    print(f"\n{'='*50}")
    print(f"Results: {stats}")


if __name__ == "__main__":
    main()
