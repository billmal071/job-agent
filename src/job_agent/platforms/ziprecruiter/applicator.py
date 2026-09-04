"""ZipRecruiter application submission."""

from __future__ import annotations

from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.platforms.ziprecruiter.selectors import SELECTORS
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class ZipRecruiterApplicator(BaseApplicator):
    """Handles ZipRecruiter job application submission."""

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        # Click the 1-Click Apply / Apply button
        apply_btn = self.page.locator(SELECTORS.apply_button).first
        if apply_btn.count() == 0:
            log.warning("no_apply_button", job_id=job.external_id)
            return False

        pages_before = list(self.page.context.pages)
        self._click_and_wait_for_popup(apply_btn)
        human_delay(2000, 4000)

        # ZipRecruiter may redirect to a company ATS — hand off to external handler
        delegated = self._delegate_external_redirect(
            "ziprecruiter.com", job, resume_path, cover_letter_path, pages_before
        )
        if delegated is not None:
            return delegated

        return self._process_apply(resume_path)

    def _process_apply(self, resume_path: str) -> bool:
        """Process ZipRecruiter's 1-Click Apply modal."""
        human_delay(1000, 2000)

        self._upload_resume(resume_path)

        submit_btn = self.page.locator(SELECTORS.submit_button).first
        if submit_btn.count() > 0:
            submit_btn.click()
            human_delay(2000, 4000)
            log.info("ziprecruiter_application_submitted")
            return True

        log.warning("ziprecruiter_apply_no_submit")
        return False
