"""Glassdoor application submission."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_delay
from job_agent.config import Settings
from job_agent.platforms.base import JobPosting
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class GlassdoorApplicator:
    """Handles Glassdoor job application submission."""

    def __init__(self, page: Page, rate_limiter: RateLimiter, settings: Settings):
        self.page = page
        self.rate_limiter = rate_limiter
        self.settings = settings

    def apply(self, job: JobPosting, resume_path: str) -> bool:
        """Apply to a job on Glassdoor."""
        if self.settings.agent.dry_run:
            log.info("dry_run_apply", job=job.title, company=job.company)
            return True

        try:
            self.rate_limiter.wait()
            self.page.goto(job.url)
            self.page.wait_for_load_state("networkidle")
            human_delay(2000, 4000)

            # Click Apply button
            apply_btn = self.page.locator(
                '[data-test="applyButton"], '
                'button:has-text("Apply"), '
                'a:has-text("Apply")'
            ).first
            if apply_btn.count() == 0:
                log.warning("no_apply_button", job_id=job.external_id)
                return False

            apply_btn.click()
            human_delay(2000, 4000)

            # Glassdoor typically redirects to company ATS
            if "glassdoor.com" not in self.page.url:
                log.info("external_ats_redirect", url=self.page.url)
                return False

            # Handle Glassdoor's apply flow if available
            file_input = self.page.locator('input[type="file"]')
            if file_input.count() > 0 and Path(resume_path).exists():
                file_input.first.set_input_files(resume_path)
                human_delay(1000, 2000)

            submit_btn = self.page.locator(
                'button[type="submit"], '
                'button:has-text("Submit")'
            ).first
            if submit_btn.count() > 0:
                submit_btn.click()
                human_delay(2000, 4000)
                log.info("glassdoor_application_submitted")
                self.rate_limiter.success()
                return True

            return False

        except Exception as e:
            log.error("glassdoor_apply_failed", job_id=job.external_id, error=str(e))
            self.rate_limiter.failure()
            return False
