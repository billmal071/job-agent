"""Dice application submission."""

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


class DiceApplicator:
    """Handles Dice job application submission."""

    def __init__(self, page: Page, rate_limiter: RateLimiter, settings: Settings):
        self.page = page
        self.rate_limiter = rate_limiter
        self.settings = settings

    def apply(self, job: JobPosting, resume_path: str) -> bool:
        """Apply to a job on Dice via Easy Apply."""
        if self.settings.agent.dry_run:
            log.info("dry_run_apply", job=job.title, company=job.company)
            return True

        try:
            self.rate_limiter.wait()
            safe_goto(self.page,job.url)
            self.page.wait_for_selector(
                "#jobDescription, [data-testid='jobDescription'], .job-description",
                timeout=15000,
            )
            human_delay(2000, 4000)

            # Click Apply / Easy Apply button
            apply_btn = self.page.locator(
                'button:has-text("Easy Apply"), '
                'button:has-text("Apply"), '
                'a[data-cy="apply-button"], '
                '[data-testid="apply-button"]'
            ).first
            if apply_btn.count() == 0:
                log.warning("no_apply_button", job_id=job.external_id)
                return False

            apply_btn.click()
            human_delay(2000, 4000)

            # Many Dice jobs redirect to external ATS (Greenhouse, Lever, Workday)
            if "dice.com" not in self.page.url:
                log.info("external_ats_redirect", url=self.page.url)
                return False

            # Handle Dice's built-in apply flow
            return self._process_dice_apply(resume_path)

        except Exception as e:
            self._take_screenshot("dice_apply_error")
            log.error("dice_apply_failed", job_id=job.external_id, error=str(e))
            self.rate_limiter.failure()
            return False

    def _process_dice_apply(self, resume_path: str) -> bool:
        """Process Dice's Easy Apply modal."""
        human_delay(1000, 2000)

        # Handle resume upload if prompted
        file_input = self.page.locator('input[type="file"]')
        if file_input.count() > 0 and Path(resume_path).exists():
            file_input.first.set_input_files(resume_path)
            human_delay(1000, 2000)

        # Multi-step form: iterate through continue/submit
        max_steps = 5
        for step in range(max_steps):
            human_delay(1000, 2000)

            submit_btn = self.page.locator(
                'button:has-text("Submit"), '
                'button:has-text("Apply"), '
                'button:has-text("Next"), '
                'button[type="submit"]'
            ).first
            if submit_btn.count() > 0:
                text = submit_btn.inner_text().strip().lower()
                if "submit" in text or "apply" in text:
                    submit_btn.click()
                    human_delay(2000, 4000)
                    log.info("dice_application_submitted")
                    self.rate_limiter.success()
                    return True
                else:
                    submit_btn.click()
                    human_delay(1500, 3000)
            else:
                break

        log.warning("dice_apply_max_steps")
        return False

    def _take_screenshot(self, name: str) -> str:
        """Take a screenshot for debugging."""
        screenshots_dir = self.settings.data_dir / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = screenshots_dir / f"{name}_{int(time.time())}.png"
        self.page.screenshot(path=str(path))
        log.info("screenshot_taken", path=str(path))
        return str(path)
