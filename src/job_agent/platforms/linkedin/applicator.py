"""LinkedIn Easy Apply form filling and submission."""

from __future__ import annotations

from pathlib import Path

from job_agent.ai.screening import FormField, ScreeningAnswerer
from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class LinkedInApplicator(BaseApplicator):
    """Handles LinkedIn Easy Apply form filling and submission."""

    _answerer: ScreeningAnswerer | None = None

    def _get_answerer(self) -> ScreeningAnswerer | None:
        """Create a ScreeningAnswerer from AI client and profile, if available."""
        if self._answerer:
            return self._answerer
        if not self._ai_client or not self._profile:
            return None
        summary = self._build_candidate_summary(self._profile)
        salary = str(self._profile.get("search", {}).get("salary_minimum", ""))
        self._answerer = ScreeningAnswerer(self._ai_client, summary, salary)
        return self._answerer

    def _dismiss_login_popup(self) -> bool:
        """Dismiss LinkedIn sign-in popup/modal if it appears. Returns True if dismissed."""
        login_modal = self.page.locator(
            '[data-test-modal-id="join-now-modal"], '
            ".join-now-modal, "
            '[role="dialog"]:has-text("Sign in"), '
            '[role="dialog"]:has-text("Join LinkedIn")'
        )
        if login_modal.count() > 0:
            close_btn = login_modal.locator(
                'button[aria-label="Dismiss"], '
                'button[aria-label="Close"], '
                'button:has-text("✕"), '
                ".artdeco-modal__dismiss"
            )
            if close_btn.count() > 0:
                close_btn.first.click()
                human_delay(500, 1000)
                log.info("login_popup_dismissed")
                return True
            # If no close button, try pressing Escape
            self.page.keyboard.press("Escape")
            human_delay(500, 1000)
            if login_modal.count() == 0:
                log.info("login_popup_dismissed_via_escape")
                return True
        return False

    def _verify_logged_in(self) -> bool:
        """Check if still logged into LinkedIn, re-auth if session expired."""
        # Look for signs we're logged out
        login_indicators = self.page.locator(
            'a[href*="/login"], '
            'button:has-text("Sign in"), '
            '.nav__button-secondary:has-text("Sign in")'
        )
        logged_in_indicators = self.page.locator(
            '.global-nav__me, nav[aria-label="Primary"], .feed-identity-module'
        )
        if logged_in_indicators.count() > 0:
            return True
        if login_indicators.count() > 0:
            log.warning("linkedin_session_expired_during_apply")
            return False
        # Ambiguous — assume logged in
        return True

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        # Dismiss any login popups that may have appeared
        self._dismiss_login_popup()

        # Verify we're still logged in
        if not self._verify_logged_in():
            log.error("cannot_apply_not_logged_in", job_id=job.external_id)
            return False

        # Wait for the page to settle and look for Easy Apply button
        # LinkedIn uses <a> tags (not <button>) for Easy Apply
        apply_btn = None
        strategies = [
            lambda: self.page.locator('[aria-label*="Easy Apply"]'),
            lambda: self.page.locator(".jobs-apply-button"),
            lambda: self.page.get_by_role("link", name="Easy Apply"),
            lambda: self.page.get_by_role("button", name="Easy Apply"),
        ]
        human_delay(2000, 3000)  # Extra settle time

        for strategy in strategies:
            try:
                btn = strategy()
                if btn.count() > 0 and btn.first.is_visible():
                    apply_btn = btn
                    break
            except Exception:
                continue

        if not apply_btn:
            # No Easy Apply — try external "Apply" link to company ATS
            external_link = self.page.locator(
                'a:has-text("Apply"), a.jobs-apply-button, a[href*="/applyredirect"]'
            ).first
            if external_link.count() > 0:
                href = external_link.get_attribute("href") or ""
                log.info("external_apply_link", url=href[:100], job_id=job.external_id)
                external_link.click()
                human_delay(3000, 5000)
                # Handle new tab/popup or redirect
                if "linkedin.com" not in self.page.url:
                    from job_agent.platforms.external_ats import ExternalATSApplicator

                    ats = ExternalATSApplicator(self.page, self._get_answerer())
                    return ats.apply(job, resume_path, cover_letter_path)
                # Check for popup/new tab
                pages = self.page.context.pages
                if len(pages) > 1:
                    new_page = pages[-1]
                    from job_agent.platforms.external_ats import ExternalATSApplicator

                    ats = ExternalATSApplicator(new_page, self._get_answerer())
                    result = ats.apply(job, resume_path, cover_letter_path)
                    new_page.close()
                    return result
            closed = self.page.locator(':text("No longer accepting")').count() > 0
            log.warning(
                "no_easy_apply_button",
                job_id=job.external_id,
                url=self.page.url,
                closed=closed,
            )
            self._take_screenshot(f"no_easy_apply_{job.external_id}")
            return False

        # Try clicking the button first
        apply_btn.first.click()
        human_delay(3000, 5000)

        # If click didn't navigate or open modal, try direct navigation
        if "/apply/" not in self.page.url:
            modal = self.page.locator(
                ".jobs-easy-apply-modal, "
                '[data-test-modal-id="easy-apply-modal"], '
                '[role="dialog"]'
            )
            if modal.count() == 0:
                # Click didn't work — try extracting the href and navigating directly
                href = apply_btn.first.get_attribute("href")
                if href:
                    log.info("navigating_to_apply_url", href=href[:100])
                    self.page.goto(href, wait_until="domcontentloaded")
                    human_delay(3000, 5000)

        self._take_screenshot(f"after_easy_apply_click_{job.external_id}")

        # Handle multi-step application flow (modal or SDUI page)
        return self._process_modal(resume_path, cover_letter_path, answers)

    def _check_success_confirmation(self) -> bool:
        """Check if LinkedIn shows an application-sent confirmation."""
        success = self.page.locator(
            ':text("Application sent"), '
            ':text("Your application was sent"), '
            ".artdeco-inline-feedback--success, "
            '[data-test-modal-id="post-apply-modal"]'
        )
        return success.count() > 0

    def _check_form_errors(self) -> list[str]:
        """Check for validation errors on the current form step."""
        errors = []
        error_els = self.page.locator(
            ".artdeco-inline-feedback--error, "
            ".fb-dash-form-element__error-field, "
            "[data-test-form-element-error], "
            ".jobs-easy-apply-form-element__error"
        ).all()
        for el in error_els:
            try:
                text = el.inner_text().strip()
                if text:
                    errors.append(text)
            except Exception:
                pass
        return errors

    def _dismiss_discard_dialog(self) -> None:
        """Dismiss the 'Discard application?' confirmation dialog."""
        discard_dialog = self.page.locator(
            '[data-test-modal-id="data-test-easy-apply-discard-confirmation"], '
            '[role="alertdialog"], '
            '[role="dialog"]:has-text("Discard")'
        )
        if discard_dialog.count() > 0:
            discard_btn = discard_dialog.locator(
                'button:has-text("Discard"), button[data-test-dialog-primary-btn]'
            )
            if discard_btn.count() > 0:
                discard_btn.first.click()
                human_delay(500, 1000)
                log.info("discard_dialog_dismissed")

    def _process_modal(
        self,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        """Process the Easy Apply modal/page steps."""
        max_steps = 10
        prev_step_html = ""

        for step in range(max_steps):
            human_delay(1500, 3000)

            # Check for success (may have been auto-submitted)
            if self._check_success_confirmation():
                log.info("application_submitted", step=step)
                return True

            # Check if we're in a modal or SDUI apply page
            modal = self.page.locator(
                ".jobs-easy-apply-modal, "
                '[data-test-modal-id="easy-apply-modal"], '
                '[role="dialog"]'
            )
            on_apply_page = "/apply/" in self.page.url

            if modal.count() == 0 and not on_apply_page:
                # Check if we landed on a success page
                if self._check_success_confirmation():
                    log.info("application_submitted", step=step)
                    return True
                log.info("modal_closed_unexpectedly", step=step, url=self.page.url)
                self._take_screenshot(f"modal_closed_{step}")
                self._dismiss_discard_dialog()
                return False

            # Handle resume upload
            self._handle_resume_upload(resume_path)

            # Handle cover letter upload
            if cover_letter_path:
                self._handle_cover_letter_upload(cover_letter_path)

            # Handle contact info (usually pre-filled)
            self._handle_contact_info()

            # Handle screening questions (AI-powered or dict-based)
            self._handle_screening_questions(answers)

            # Check for submit button (both modal and SDUI selectors)
            submit_btn = self.page.locator(
                '[aria-label="Submit application"], '
                '[aria-label="Review your application"], '
                'button:has-text("Submit application"), '
                'button:has-text("Submit")'
            )
            if submit_btn.count() > 0:
                text = submit_btn.first.inner_text().strip().lower()
                aria = (submit_btn.first.get_attribute("aria-label") or "").lower()
                if "review" in text or "review" in aria:
                    submit_btn.first.click()
                    human_delay(2000, 4000)
                    # Now click the final submit
                    final_submit = self.page.locator(
                        '[aria-label="Submit application"], '
                        'button:has-text("Submit application"), '
                        'button:has-text("Submit")'
                    )
                    if final_submit.count() > 0:
                        final_submit.first.click()
                        human_delay(3000, 5000)
                        if self._check_success_confirmation():
                            log.info("application_submitted")
                            return True
                        # Check for errors after submit
                        errors = self._check_form_errors()
                        if errors:
                            log.warning("submit_validation_errors", errors=errors)
                            self._take_screenshot(f"submit_errors_{step}")
                            self._dismiss_discard_dialog()
                            return False
                        # Assume success if no errors and modal closed
                        log.info("application_submitted")
                        return True
                else:
                    submit_btn.first.click()
                    human_delay(3000, 5000)
                    if self._check_success_confirmation():
                        log.info("application_submitted")
                        return True
                    log.info("application_submitted")
                    return True

            # Click Next to proceed to next step
            next_btn = self.page.locator(
                '[aria-label="Continue to next step"], '
                '[aria-label="Next"], '
                'button:has-text("Next"), '
                'button:has-text("Continue")'
            )
            if next_btn.count() > 0:
                # Capture current state to detect if Next actually advanced
                try:
                    cur_html = (
                        modal.first.inner_html()[:200] if modal.count() > 0 else ""
                    )
                except Exception:
                    cur_html = ""

                next_btn.first.click()
                human_delay(2000, 3000)

                # Check for validation errors (Next didn't advance)
                errors = self._check_form_errors()
                if errors:
                    log.warning(
                        "next_validation_errors",
                        step=step,
                        errors=errors,
                    )
                    self._take_screenshot(f"validation_errors_{step}")
                    # Try to fill required fields again
                    self._handle_screening_questions(answers)
                    human_delay(500, 1000)
                    # Retry Next
                    if next_btn.count() > 0:
                        next_btn.first.click()
                        human_delay(2000, 3000)
                        errors2 = self._check_form_errors()
                        if errors2:
                            log.error("cannot_resolve_form_errors", errors=errors2)
                            self._dismiss_discard_dialog()
                            return False

                # Detect if page didn't change (stuck)
                try:
                    new_html = (
                        modal.first.inner_html()[:200] if modal.count() > 0 else ""
                    )
                except Exception:
                    new_html = ""
                if new_html and new_html == cur_html == prev_step_html:
                    log.warning("modal_stuck_same_content", step=step)
                    self._take_screenshot(f"modal_stuck_{step}")
                    self._dismiss_discard_dialog()
                    return False
                prev_step_html = cur_html
            else:
                log.warning("no_next_or_submit_button", step=step)
                self._take_screenshot(f"no_next_submit_{step}")
                self._dismiss_discard_dialog()
                break

        log.error("max_steps_exceeded")
        self._dismiss_discard_dialog()
        return False

    def _handle_resume_upload(self, resume_path: str) -> None:
        """Upload resume if a file input is present."""
        file_input = self.page.locator('input[type="file"]')
        if file_input.count() > 0 and Path(resume_path).exists():
            # Check if there's already a resume uploaded
            existing = self.page.locator(
                ".jobs-document-upload-redesign-card__file-name, "
                ".jobs-document-upload__file-name, "
                ".jobs-resume-upload__file-name"
            )
            if existing.count() == 0:
                file_input.first.set_input_files(resume_path)
                human_delay(1000, 2000)
                log.info("resume_uploaded", path=resume_path)

    def _handle_cover_letter_upload(self, cover_letter_path: str) -> None:
        """Upload cover letter if applicable."""
        cover_section = self.page.locator('text="Cover letter", text="cover letter"')
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

    def _handle_screening_questions(self, answers: dict[str, str] | None) -> None:
        """Answer screening questions using AI or provided answers dict."""
        questions = self.page.locator(
            ".jobs-easy-apply-form-section__grouping, "
            ".jobs-easy-apply-form-element, "
            ".fb-dash-form-element"
        ).all()

        if not questions:
            return

        answerer = self._get_answerer()

        for question_group in questions:
            try:
                label_el = question_group.locator("label, legend, span.t-14").first
                if label_el.count() == 0:
                    continue
                label = label_el.inner_text().strip()
                if not label:
                    continue

                # Try dict-based answers first (backward compatible)
                if answers:
                    matched = self._try_dict_answer(question_group, label, answers)
                    if matched:
                        continue

                # Use AI-powered answering
                if answerer:
                    field = self._parse_linkedin_field_group(question_group, label)
                    if field:
                        try:
                            answer = answerer.answer_field(field)
                            self._fill_field(field, answer)
                        except Exception as e:
                            log.warning(
                                "screening_fill_error",
                                label=field.label,
                                error=str(e),
                            )
            except Exception as e:
                log.debug("screening_question_error", error=str(e))

    def _try_dict_answer(self, group, label: str, answers: dict[str, str]) -> bool:
        """Try to answer a question from the static answers dict. Returns True if matched."""
        label_lower = label.lower()
        for key, value in answers.items():
            if key.lower() in label_lower:
                # Try text input
                text_input = group.locator('input[type="text"], textarea').first
                if text_input.count() > 0:
                    text_input.fill(value)
                    return True

                # Try select dropdown
                select_el = group.locator("select").first
                if select_el.count() > 0:
                    select_el.select_option(label=value)
                    return True

                # Try radio buttons
                radio = group.locator(f'input[type="radio"][value="{value}"]').first
                if radio.count() > 0:
                    radio.click()
                    return True
        return False

    def _parse_linkedin_field_group(self, group, label: str) -> FormField | None:
        """Parse a LinkedIn form group into a FormField."""
        # Check for select
        select = group.locator("select").first
        if select.count() > 0:
            options = []
            for opt in group.locator("select option").all():
                text = opt.inner_text().strip()
                val = opt.get_attribute("value") or ""
                if text and val:
                    options.append(text)
            el_id = select.get_attribute("id") or ""
            selector = f"#{el_id}" if el_id else ""
            return FormField(
                label=label,
                field_type="select",
                options=options,
                selector=selector,
            )

        # Check for radio buttons
        radios = group.locator('input[type="radio"]')
        if radios.count() > 0:
            options = []
            for radio in radios.all():
                radio_id = radio.get_attribute("id") or ""
                if radio_id:
                    assoc = group.locator(f'label[for="{radio_id}"]')
                    if assoc.count() > 0:
                        options.append(assoc.inner_text().strip())
                        continue
                val = radio.get_attribute("value") or ""
                if val:
                    options.append(val)
            # Use parent fieldset or group as selector for radios
            fieldset_id = group.get_attribute("id") or ""
            selector = f"#{fieldset_id}" if fieldset_id else ""
            return FormField(
                label=label,
                field_type="radio",
                options=options,
                selector=selector,
            )

        # Check for textarea
        textarea = group.locator("textarea").first
        if textarea.count() > 0:
            el_id = textarea.get_attribute("id") or ""
            selector = f"#{el_id}" if el_id else ""
            return FormField(
                label=label,
                field_type="textarea",
                selector=selector,
                current_value=textarea.input_value(),
            )

        # Check for text/number input
        text_input = group.locator(
            'input[type="text"], input[type="number"], input:not([type])'
        ).first
        if text_input.count() > 0:
            input_type = text_input.get_attribute("type") or "text"
            el_id = text_input.get_attribute("id") or ""
            selector = f"#{el_id}" if el_id else ""
            return FormField(
                label=label,
                field_type="number" if input_type == "number" else "text",
                selector=selector,
                current_value=text_input.input_value(),
            )

        return None
