"""LinkedIn Easy Apply form filling and submission."""

from __future__ import annotations

from pathlib import Path

from job_agent.browser.humanizer import human_click, human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class LinkedInApplicator(BaseApplicator):
    """Handles LinkedIn Easy Apply form filling and submission."""

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        # Click Easy Apply button
        apply_btn = self.page.locator(
            ".jobs-apply-button, "
            'button[aria-label*="Easy Apply"]'
        )
        if apply_btn.count() == 0:
            log.warning("no_easy_apply_button", job_id=job.external_id)
            return False

        human_click(self.page, ".jobs-apply-button")
        human_delay(1500, 3000)

        # Handle multi-step modal
        return self._process_modal(resume_path, cover_letter_path, answers)

    def _process_modal(
        self,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        """Process the Easy Apply modal steps."""
        max_steps = 10

        for step in range(max_steps):
            human_delay(1000, 2000)

            # Check if modal is still open
            modal = self.page.locator(
                ".jobs-easy-apply-modal, "
                '[data-test-modal-id="easy-apply-modal"]'
            )
            if modal.count() == 0:
                log.info("modal_closed_unexpectedly", step=step)
                return False

            # Handle resume upload
            self._handle_resume_upload(resume_path)

            # Handle cover letter upload
            if cover_letter_path:
                self._handle_cover_letter_upload(cover_letter_path)

            # Handle contact info (usually pre-filled)
            self._handle_contact_info()

            # Handle screening questions
            if answers:
                self._handle_screening_questions(answers)

            # Check for submit button
            submit_btn = self.page.locator(
                'button[aria-label="Submit application"], '
                'button[aria-label="Review your application"]'
            )
            if submit_btn.count() > 0:
                label = submit_btn.get_attribute("aria-label") or ""
                if "Review" in label:
                    human_click(
                        self.page,
                        'button[aria-label="Review your application"]',
                    )
                    human_delay(1500, 3000)
                    # Now click the final submit
                    final_submit = self.page.locator(
                        'button[aria-label="Submit application"]'
                    )
                    if final_submit.count() > 0:
                        human_click(
                            self.page,
                            'button[aria-label="Submit application"]',
                        )
                        human_delay(2000, 4000)
                        log.info("application_submitted")
                        return True
                else:
                    human_click(
                        self.page,
                        'button[aria-label="Submit application"]',
                    )
                    human_delay(2000, 4000)
                    log.info("application_submitted")
                    return True

            # Click Next to proceed to next step
            next_btn = self.page.locator(
                'button[aria-label="Continue to next step"], '
                'button[aria-label="Next"]'
            )
            if next_btn.count() > 0:
                human_click(
                    self.page,
                    'button[aria-label="Continue to next step"]',
                )
                human_delay(1000, 2000)
            else:
                log.warning("no_next_or_submit_button", step=step)
                break

        log.error("max_steps_exceeded")
        return False

    def _handle_resume_upload(self, resume_path: str) -> None:
        """Upload resume if a file input is present."""
        file_input = self.page.locator('input[type="file"]')
        if file_input.count() > 0 and Path(resume_path).exists():
            # Check if there's already a resume uploaded
            existing = self.page.locator(
                ".jobs-document-upload-redesign-card__file-name"
            )
            if existing.count() == 0:
                file_input.first.set_input_files(resume_path)
                human_delay(1000, 2000)
                log.info("resume_uploaded", path=resume_path)

    def _handle_cover_letter_upload(self, cover_letter_path: str) -> None:
        """Upload cover letter if applicable."""
        cover_section = self.page.locator(
            'text="Cover letter", text="cover letter"'
        )
        if cover_section.count() > 0 and Path(cover_letter_path).exists():
            file_inputs = self.page.locator('input[type="file"]').all()
            if len(file_inputs) > 1:
                file_inputs[1].set_input_files(cover_letter_path)
                human_delay(1000, 2000)
                log.info("cover_letter_uploaded", path=cover_letter_path)

    def _handle_contact_info(self) -> None:
        """Fill in contact information fields if empty."""
        for selector in ('input[name="phone"]', 'input[name="email"]'):
            el = self.page.locator(selector)
            if el.count() > 0:
                value = el.input_value()
                if not value:
                    log.warning("empty_contact_field", field=selector)

    def _handle_screening_questions(self, answers: dict[str, str]) -> None:
        """Answer screening questions using provided answers."""
        questions = self.page.locator(
            ".jobs-easy-apply-form-section__grouping"
        ).all()

        for question in questions:
            try:
                label_el = question.locator("label, legend, span.t-14").first
                if label_el.count() == 0:
                    continue
                label = label_el.inner_text().strip().lower()

                for key, value in answers.items():
                    if key.lower() in label:
                        # Try text input
                        text_input = question.locator(
                            'input[type="text"], textarea'
                        ).first
                        if text_input.count() > 0:
                            text_input.fill(value)
                            break

                        # Try select dropdown
                        select_el = question.locator("select").first
                        if select_el.count() > 0:
                            select_el.select_option(label=value)
                            break

                        # Try radio buttons
                        radio = question.locator(
                            f'input[type="radio"][value="{value}"]'
                        ).first
                        if radio.count() > 0:
                            radio.click()
                            break
            except Exception as e:
                log.debug("screening_question_error", error=str(e))
