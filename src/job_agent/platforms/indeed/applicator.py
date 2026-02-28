"""Indeed application submission."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_delay
from job_agent.config import Settings
from job_agent.platforms.base import JobPosting
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class IndeedApplicator:
    """Handles Indeed job application submission."""

    def __init__(self, page: Page, rate_limiter: RateLimiter, settings: Settings):
        self.page = page
        self.rate_limiter = rate_limiter
        self.settings = settings

    def apply(self, job: JobPosting, resume_path: str) -> bool:
        """Apply to a job on Indeed."""
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
                '#indeedApplyButton, '
                'button[id*="apply"], '
                'a[href*="apply"]'
            ).first
            if apply_btn.count() == 0:
                log.warning("no_apply_button", job_id=job.external_id)
                return False

            apply_btn.click()
            human_delay(2000, 4000)

            # Indeed often redirects to company ATS
            # Check if we're on Indeed's apply flow or external
            if "indeed.com" not in self.page.url:
                log.info("external_ats_redirect", url=self.page.url)
                # Handle external ATS is complex - mark as needing manual review
                return False

            # Handle Indeed's built-in apply flow
            return self._process_indeed_apply(resume_path)

        except Exception as e:
            log.error("indeed_apply_failed", job_id=job.external_id, error=str(e))
            self.rate_limiter.failure()
            return False

    def _process_indeed_apply(self, resume_path: str) -> bool:
        """Process Indeed's multi-step apply flow."""
        max_steps = 8

        for step in range(max_steps):
            human_delay(1000, 2000)

            # Handle resume upload
            file_input = self.page.locator('input[type="file"]')
            if file_input.count() > 0 and Path(resume_path).exists():
                file_input.first.set_input_files(resume_path)
                human_delay(1000, 2000)

            # Look for continue/submit button
            continue_btn = self.page.locator(
                'button[id*="continue"], '
                'button:has-text("Continue"), '
                'button:has-text("Submit")'
            ).first
            if continue_btn.count() > 0:
                text = continue_btn.inner_text().strip().lower()
                if "submit" in text:
                    continue_btn.click()
                    human_delay(2000, 4000)
                    log.info("indeed_application_submitted")
                    self.rate_limiter.success()
                    return True
                else:
                    continue_btn.click()
                    human_delay(1500, 3000)
            else:
                break

        log.warning("indeed_apply_max_steps")
        return False
