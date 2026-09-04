"""Glassdoor application submission."""

from __future__ import annotations

from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.platforms.glassdoor.selectors import SELECTORS
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class GlassdoorApplicator(BaseApplicator):
    """Handles Glassdoor job application submission."""

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        # Click Apply button
        apply_btn = self.page.locator(SELECTORS.apply_button).first
        if apply_btn.count() == 0:
            log.warning("no_apply_button", job_id=job.external_id)
            return False

        pages_before = list(self.page.context.pages)
        apply_btn.click()
        human_delay(2000, 4000)

        # Glassdoor redirects to company ATS — hand off to external handler
        delegated = self._delegate_external_redirect(
            "glassdoor.com", job, resume_path, cover_letter_path, pages_before
        )
        if delegated is not None:
            return delegated

        # Handle Glassdoor's native apply flow
        self._upload_resume(resume_path)

        submit_btn = self.page.locator(SELECTORS.submit_button).first
        if submit_btn.count() > 0:
            submit_btn.click()
            human_delay(2000, 4000)
            log.info("glassdoor_application_submitted")
            return True

        return False
