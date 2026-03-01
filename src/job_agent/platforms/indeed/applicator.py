"""Indeed application submission."""

from __future__ import annotations

from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class IndeedApplicator(BaseApplicator):
    """Handles Indeed job application submission."""

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
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
        if "indeed.com" not in self.page.url:
            log.info("external_ats_redirect", url=self.page.url)
            return False

        # Handle Indeed's built-in apply flow
        return self._process_indeed_apply(resume_path)

    def _process_indeed_apply(self, resume_path: str) -> bool:
        """Process Indeed's multi-step apply flow."""
        max_steps = 8

        for step in range(max_steps):
            human_delay(1000, 2000)

            # Handle resume upload
            self._upload_resume(resume_path)

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
                    return True
                else:
                    continue_btn.click()
                    human_delay(1500, 3000)
            else:
                break

        log.warning("indeed_apply_max_steps")
        return False
