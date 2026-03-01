"""Wellfound application submission."""

from __future__ import annotations

from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class WellfoundApplicator(BaseApplicator):
    """Handles Wellfound job application submission."""

    def _navigate_to_job(self, job: JobPosting) -> None:
        """Wellfound needs to wait for job description element."""
        from job_agent.platforms.base import safe_goto

        safe_goto(self.page, job.url)
        self.page.wait_for_selector(
            '[data-test="job-description"], .job-description, .description',
            timeout=15000,
        )

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
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

        return self._process_wellfound_apply(resume_path)

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

        self._upload_resume(resume_path)

        submit_btn = self.page.locator(
            'button:has-text("Submit Application"), '
            'button:has-text("Submit"), '
            'button[type="submit"]'
        ).first
        if submit_btn.count() > 0:
            submit_btn.click()
            human_delay(2000, 4000)
            log.info("wellfound_application_submitted")
            return True

        log.warning("wellfound_apply_no_submit")
        return False
