"""Wellfound application submission."""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_delay
from job_agent.config import Settings
from job_agent.platforms.base import JobPosting, safe_goto
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class WellfoundApplicator:
    """Handles Wellfound job application submission."""

    def __init__(self, page: Page, rate_limiter: RateLimiter, settings: Settings):
        self.page = page
        self.rate_limiter = rate_limiter
        self.settings = settings

    def apply(self, job: JobPosting, resume_path: str) -> bool:
        """Apply to a job on Wellfound."""
        if self.settings.agent.dry_run:
            log.info("dry_run_apply", job=job.title, company=job.company)
            return True

        try:
            self.rate_limiter.wait()
            safe_goto(self.page,job.url)
            self.page.wait_for_selector(
                '[data-test="job-description"], .job-description, .description',
                timeout=15000,
            )
            human_delay(2000, 4000)

            # Click Apply button
            apply_btn = self.page.locator(
                'button:has-text("Apply"), '
                'a:has-text("Apply Now"), '
                '[data-test="apply-button"]'
            ).first
            if apply_btn.count() == 0:
                log.warning("no_apply_button", job_id=job.external_id)
                return False

            apply_btn.click()
            human_delay(2000, 4000)

            # Wellfound uses built-in apply — no external ATS redirect
            return self._process_wellfound_apply(resume_path)

        except Exception as e:
            self._take_screenshot("wellfound_apply_error")
            log.error("wellfound_apply_failed", job_id=job.external_id, error=str(e))
            self.rate_limiter.failure()
            return False

    def _process_wellfound_apply(self, resume_path: str) -> bool:
        """Process Wellfound's apply flow."""
        human_delay(1000, 2000)

        # Fill cover note if textarea is present
        cover_note = self.page.locator(
            'textarea[name="coverLetter"], textarea[data-test="cover-letter"], textarea'
        )
        if cover_note.count() > 0:
            cover_note.first.fill(self.settings.resume.default_cover_note)
            human_delay(500, 1000)

        # Handle resume upload if prompted
        file_input = self.page.locator('input[type="file"]')
        if file_input.count() > 0 and Path(resume_path).exists():
            file_input.first.set_input_files(resume_path)
            human_delay(1000, 2000)

        # Submit
        submit_btn = self.page.locator(
            'button:has-text("Submit Application"), '
            'button:has-text("Submit"), '
            'button[type="submit"]'
        ).first
        if submit_btn.count() > 0:
            submit_btn.click()
            human_delay(2000, 4000)
            log.info("wellfound_application_submitted")
            self.rate_limiter.success()
            return True

        log.warning("wellfound_apply_no_submit")
        return False

    def _take_screenshot(self, name: str) -> str:
        """Take a screenshot for debugging."""
        screenshots_dir = self.settings.data_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = screenshots_dir / f"{name}_{int(time.time())}.png"
        self.page.screenshot(path=str(path))
        log.info("screenshot_taken", path=str(path))
        return str(path)
