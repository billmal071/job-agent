"""Login to Indeed via Camoufox, then apply to approved jobs.

Step 1: Login with email — user completes OTP manually
Step 2: Save session state
Step 3: Navigate to each job and apply via smartapply.indeed.com
"""
import sys
import json
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
from job_agent.db.repository import ApplicationRepository, CredentialRepository, JobRepository
from job_agent.db.session import get_session
from job_agent.platforms.base import JobPosting
from job_agent.platforms.external_ats import ExternalATSApplicator
from job_agent.browser.humanizer import human_delay
from job_agent.utils.crypto import decrypt
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

STATE_FILE = Path("~/.job-agent/browser_state/indeed_camoufox.json").expanduser()


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


def login_indeed(browser, username):
    """Load Indeed session from saved state, or prompt for interactive login."""
    if not STATE_FILE.exists():
        print("ERROR: No saved session. Run scripts/indeed_login_only.py first.")
        sys.exit(1)

    print(f"Loading session from {STATE_FILE}")
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        storage_state=str(STATE_FILE),
    )
    page = ctx.new_page()

    # Verify session works
    page.goto("https://www.indeed.com/viewjob?jk=162a100fceae998c", timeout=60000, wait_until="commit")
    time.sleep(5)

    # Wait through Cloudflare challenge
    for _ in range(12):
        title = page.title().lower()
        if "just a moment" not in title:
            break
        print("  Waiting for Cloudflare...")
        time.sleep(5)

    title = page.title().lower()
    if "security check" in title or "additional verification" in title:
        print("ERROR: Saved session expired/blocked. Run scripts/indeed_login_only.py again.")
        sys.exit(1)
    if "just a moment" in title:
        print("ERROR: Stuck on Cloudflare. Try again later.")
        sys.exit(1)

    print(f"Session loaded OK: {page.title()}")
    return ctx, page


def dismiss_modals(page):
    """Dismiss Indeed popups."""
    try:
        page.evaluate("""
            var el = document.querySelector('#credential_picker_container');
            if (el) el.remove();
            document.querySelectorAll('iframe[src*="accounts.google.com"]').forEach(e => e.remove());
            document.querySelectorAll('[role="dialog"] button[aria-label="close"]').forEach(b => b.click());
        """)
    except Exception:
        pass


def apply_to_job(page, ctx, job, posting, resume_path, cl_path, answerer):
    """Navigate to job and apply."""
    import re
    jk = ""
    url = job.url or ""
    m = re.search(r"jk=([a-f0-9]+)", url)
    if m:
        jk = m.group(1)
    if not jk:
        return "skip", "No job key"

    viewjob_url = f"https://www.indeed.com/viewjob?jk={jk}"
    page.goto(viewjob_url, timeout=60000, wait_until="commit")
    human_delay(3000, 5000)

    # Wait through Cloudflare challenge
    for _ in range(12):
        if "just a moment" not in page.title().lower():
            break
        time.sleep(5)

    dismiss_modals(page)
    human_delay(1000, 2000)

    # Check for Cloudflare (still stuck after waiting)
    if "just a moment" in page.title().lower():
        return "skip", "Cloudflare"

    # Find Apply button and extract its href
    apply_btn = page.locator(
        'button:has-text("Apply now"), '
        'button:has-text("Apply on company site"), '
        'button:has-text("Apply"), '
        '#indeedApplyButton'
    ).first
    if apply_btn.count() == 0:
        return "skip", "No apply button"

    btn_text = apply_btn.inner_text().strip()
    apply_href = apply_btn.get_attribute("href") or ""
    print(f"    Button: '{btn_text}' href={apply_href[:80]}")

    # Use a NEW page/tab to navigate to the apply URL.
    # The button tries to open a new tab (which Camoufox may block),
    # so we open a new page ourselves and navigate there.
    target_page = ctx.new_page()
    if apply_href:
        if not apply_href.startswith("http"):
            apply_href = f"https://www.indeed.com{apply_href}"
        try:
            target_page.goto(apply_href, timeout=45000, wait_until="domcontentloaded")
        except Exception as e:
            print(f"    Navigation timeout, checking URL anyway...")
        human_delay(3000, 5000)
    else:
        # No href — try clicking the button
        pages_before = len(ctx.pages)
        try:
            apply_btn.click(force=True, timeout=15000)
        except Exception as e:
            print(f"    Click timeout: {e}")
        human_delay(5000, 8000)
        if len(ctx.pages) > pages_before:
            target_page = ctx.pages[-1]
        else:
            target_page.close()
            return "skip", "Click did not navigate"

    current = target_page.url
    print(f"    Landed on: {current[:80]}")

    # Wait for Cloudflare challenge if present
    if "just a moment" in target_page.title().lower():
        print("    Waiting for Cloudflare...")
        for _ in range(12):
            time.sleep(5)
            if "just a moment" not in target_page.title().lower():
                break
        current = target_page.url

    if "smartapply.indeed.com" in current:
        # Indeed's own apply flow
        # Check for Cloudflare on smartapply
        if "just a moment" in target_page.title().lower():
            print("    Waiting for Cloudflare on smartapply...")
            for _ in range(12):
                time.sleep(5)
                if "just a moment" not in target_page.title().lower():
                    break

            if "just a moment" in target_page.title().lower():
                if target_page != page:
                    target_page.close()
                return "skip", "Cloudflare on smartapply"

        # Process Indeed SmartApply form
        result = process_smartapply(target_page, resume_path, answerer)
        if target_page != page:
            target_page.close()
        return ("success", "SmartApply") if result else ("fail", "SmartApply incomplete")

    elif "indeed.com" not in current:
        # External ATS
        ats = ExternalATSApplicator(target_page, answerer)
        result = ats.apply(posting, resume_path, cl_path)
        if target_page != page:
            target_page.close()
        return ("success", "External ATS") if result else ("fail", "External ATS failed")

    if target_page != page:
        target_page.close()
    return "skip", f"Still on Indeed: {current[:60]}"


def process_smartapply(page, resume_path, answerer):
    """Handle Indeed's SmartApply multi-step flow."""
    max_steps = 8

    for step in range(max_steps):
        human_delay(2000, 3000)

        # Upload resume
        file_input = page.locator('input[type="file"]')
        if file_input.count() > 0 and Path(resume_path).exists():
            try:
                file_input.first.set_input_files(resume_path)
                human_delay(1000, 2000)
            except Exception:
                pass

        # Fill fields if answerer available
        if answerer:
            from job_agent.ai.screening import FormField
            # Look for questions
            questions = page.locator('.ia-Questions-item, .ia-BasePage-field, fieldset').all()
            for q in questions:
                try:
                    label_el = q.locator("label, legend").first
                    if label_el.count() == 0:
                        continue
                    label = label_el.inner_text().strip()
                    if not label:
                        continue

                    # Check for text input
                    inp = q.locator('input[type="text"], input[type="number"], textarea').first
                    if inp.count() > 0:
                        current = inp.input_value()
                        if current and current.strip():
                            continue
                        field = FormField(label=label, field_type="text", selector="")
                        answer = answerer.answer_field(field)
                        inp.fill(answer.answer)
                        human_delay(200, 500)

                    # Check for select
                    sel = q.locator("select").first
                    if sel.count() > 0:
                        options = [o.inner_text().strip() for o in q.locator("select option").all()]
                        field = FormField(label=label, field_type="select", options=options, selector="")
                        answer = answerer.answer_field(field)
                        try:
                            sel.select_option(label=answer.answer)
                        except Exception:
                            for opt in options:
                                if answer.answer.lower() in opt.lower():
                                    sel.select_option(label=opt)
                                    break
                except Exception:
                    continue

        # Click Continue or Submit
        submit = page.locator(
            'button:has-text("Submit"), '
            'button:has-text("Submit your application")'
        ).first
        if submit.count() > 0 and submit.is_visible():
            submit.click(force=True)
            human_delay(3000, 5000)

            # Check success
            body = page.locator("body").inner_text().lower()
            if any(p in body for p in ("application submitted", "thank you", "received your application")):
                return True
            continue

        cont = page.locator(
            'button:has-text("Continue"), '
            'button:has-text("Next"), '
            'button[data-testid="continue-button"]'
        ).first
        if cont.count() > 0 and cont.is_visible():
            cont.click(force=True)
            human_delay(2000, 3000)
            continue

        break

    return False


def main():
    settings = Settings()
    profile = load_profile("config/profiles/example.yaml")
    ai_client = AIClient(settings)
    resume_tailor = ResumeTailor(ai_client, settings)
    cover_letter_gen = CoverLetterGenerator(ai_client, settings)
    candidate_summary = build_candidate_summary(profile)
    salary = str(profile.get("search", {}).get("salary_minimum", ""))
    answerer = ScreeningAnswerer(ai_client, candidate_summary, salary)

    db_session = get_session(settings)
    job_repo = JobRepository(db_session)
    app_repo = ApplicationRepository(db_session)
    cred = CredentialRepository(db_session).get(Platform.INDEED)
    if not cred:
        print("No Indeed credentials found!")
        return

    username = cred.username

    approved = job_repo.list_by_status(JobStatus.APPROVED)
    indeed_jobs = [j for j in approved if j.platform == Platform.INDEED]
    print(f"Indeed approved jobs: {len(indeed_jobs)}")

    if not indeed_jobs:
        print("No Indeed jobs to apply to.")
        return

    stats = {"applied": 0, "failed": 0, "skipped": 0}

    with Camoufox(headless=False, humanize=True) as browser:
        ctx, page = login_indeed(browser, username)

        for i, job in enumerate(indeed_jobs, 1):
            print(f"\n[{i}/{len(indeed_jobs)}] {job.title} @ {job.company}")

            try:
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

                # Reuse existing resume/cover letter if available
                jk = ""
                import re as _re
                _m = _re.search(r"jk=([a-f0-9]+)", job.url or "")
                if _m:
                    jk = _m.group(1)
                resume_dir = Path("~/.job-agent/resumes").expanduser()
                cl_dir = Path("~/.job-agent/cover_letters").expanduser()
                existing_resume = list(resume_dir.glob(f"*{jk}*")) if jk else []
                existing_cl = list(cl_dir.glob(f"*{jk}*")) if jk else []

                if existing_resume:
                    resume_path = str(existing_resume[0])
                    print(f"  Reusing resume: {existing_resume[0].name}")
                else:
                    resume_path = resume_tailor.tailor_and_save(posting, matched_skills)

                if existing_cl:
                    cl_path = str(existing_cl[0])
                else:
                    try:
                        cl_path = cover_letter_gen.generate_and_save(
                            posting, candidate_summary, matched_skills
                        )
                    except Exception as e:
                        log.warning("cover_letter_failed", error=str(e))
                        cl_path = ""

                result, detail = apply_to_job(page, ctx, job, posting, resume_path, cl_path, answerer)

                if result == "success":
                    job.status = JobStatus.APPLIED
                    app_repo.create(job_id=job.id, resume_path=resume_path, cover_letter_path=cl_path)
                    stats["applied"] += 1
                    print(f"  SUCCESS: {detail}")
                elif result == "fail":
                    # Don't mark as failed — leave APPROVED for retry
                    stats["failed"] += 1
                    print(f"  FAILED: {detail}")
                else:
                    stats["skipped"] += 1
                    print(f"  SKIPPED: {detail}")

            except Exception as e:
                err = str(e)
                log.error("apply_error", job_id=job.id, error=err)
                if "NS_ERROR_UNKNOWN_HOST" in err or "name resolution" in err.lower():
                    # DNS failure — wait and retry
                    print(f"  DNS ERROR — waiting 30s for network...")
                    time.sleep(30)
                    stats["failed"] += 1
                else:
                    stats["failed"] += 1
                    print(f"  ERROR: {err[:100]}")

            db_session.commit()
            human_delay(2000, 4000)

        page.close()
        ctx.close()

    db_session.close()
    print(f"\n{'='*50}")
    print(f"Results: {stats}")


if __name__ == "__main__":
    main()
