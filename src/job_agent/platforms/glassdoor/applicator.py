"""Glassdoor application submission."""

from __future__ import annotations

from job_agent.ai.screening import ScreeningAnswerer
from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.platforms.external_ats import ExternalATSApplicator
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class GlassdoorApplicator(BaseApplicator):
    """Handles Glassdoor job application submission."""

    _answerer: ScreeningAnswerer | None = None

    def _get_answerer(self) -> ScreeningAnswerer | None:
        if self._answerer:
            return self._answerer
        if not self._ai_client or not self._profile:
            return None
        summary = self._build_candidate_summary(self._profile)
        salary = str(self._profile.get("search", {}).get("salary_minimum", ""))
        self._answerer = ScreeningAnswerer(self._ai_client, summary, salary)
        return self._answerer

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        # Click Apply button
        apply_btn = self.page.locator(
            '[data-test="applyButton"], button:has-text("Apply"), a:has-text("Apply")'
        ).first
        if apply_btn.count() == 0:
            log.warning("no_apply_button", job_id=job.external_id)
            return False

        apply_btn.click()
        human_delay(2000, 4000)

        # Glassdoor redirects to company ATS — hand off to external handler
        if "glassdoor.com" not in self.page.url:
            log.info("external_ats_redirect", url=self.page.url)
            ats_applicator = ExternalATSApplicator(self.page, self._get_answerer())
            return ats_applicator.apply(job, resume_path, cover_letter_path)

        # Handle Glassdoor's native apply flow
        self._upload_resume(resume_path)

        submit_btn = self.page.locator(
            'button[type="submit"], button:has-text("Submit")'
        ).first
        if submit_btn.count() > 0:
            submit_btn.click()
            human_delay(2000, 4000)
            log.info("glassdoor_application_submitted")
            return True

        return False
