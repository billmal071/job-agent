"""Dice application submission."""

from __future__ import annotations

from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class DiceApplicator(BaseApplicator):
    """Handles Dice job application submission."""

    def _navigate_to_job(self, job: JobPosting) -> None:
        """Dice needs to wait for the job description element."""
        from job_agent.platforms.base import safe_goto

        safe_goto(self.page, job.url)
        self.page.wait_for_selector(
            "#jobDescription, [data-testid='jobDescription'], .job-description",
            timeout=15000,
        )

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
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

        # Many Dice jobs redirect to external ATS
        if "dice.com" not in self.page.url:
            log.info("external_ats_redirect", url=self.page.url)
            return False

        return self._process_dice_apply(resume_path)

    def _process_dice_apply(self, resume_path: str) -> bool:
        """Process Dice's Easy Apply modal."""
        human_delay(1000, 2000)

        self._upload_resume(resume_path)

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
                    return True
                else:
                    submit_btn.click()
                    human_delay(1500, 3000)
            else:
                break

        log.warning("dice_apply_max_steps")
        return False
