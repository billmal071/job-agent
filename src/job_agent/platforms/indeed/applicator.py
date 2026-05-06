"""Indeed application submission with AI-powered screening question handling."""

from __future__ import annotations

from job_agent.ai.screening import FormField, ScreeningAnswerer
from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator
from job_agent.platforms.indeed.selectors import SELECTORS
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class IndeedApplicator(BaseApplicator):
    """Handles Indeed job application submission."""

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

    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        # If we were redirected to an external ATS already (rc/clk URLs do this),
        # handle it immediately
        if "indeed.com" not in self.page.url:
            log.info("external_ats_redirect", url=self.page.url)
            from job_agent.platforms.external_ats import ExternalATSApplicator

            ats_applicator = ExternalATSApplicator(self.page, self._get_answerer())
            return ats_applicator.apply(job, resume_path, cover_letter_path)

        # Click Apply button — try Indeed native first, then external link
        apply_btn = self.page.locator(SELECTORS.apply_button).first
        if apply_btn.count() == 0:
            # Non-easy-apply: look for "Apply on company site" link
            external_link = self.page.locator(SELECTORS.external_apply_link).first
            if external_link.count() > 0:
                href = external_link.get_attribute("href") or ""
                log.info("external_apply_link", url=href, job_id=job.external_id)
                # Track pages before click (might open new tab)
                pages_before = len(self.page.context.pages)
                external_link.click(force=True)
                human_delay(3000, 5000)

                # Check for new tab
                from job_agent.platforms.external_ats import ExternalATSApplicator

                if len(self.page.context.pages) > pages_before:
                    new_page = self.page.context.pages[-1]
                    if "indeed.com" not in new_page.url:
                        ats = ExternalATSApplicator(new_page, self._get_answerer())
                        result = ats.apply(job, resume_path, cover_letter_path)
                        new_page.close()
                        return result
                # Same tab redirect
                if "indeed.com" not in self.page.url:
                    ats = ExternalATSApplicator(self.page, self._get_answerer())
                    return ats.apply(job, resume_path, cover_letter_path)
                # Still on Indeed — try the built-in apply flow
                return self._process_indeed_apply(resume_path)
            else:
                log.warning("no_apply_button", job_id=job.external_id)
                return False

        apply_btn.click()
        human_delay(2000, 4000)

        # Indeed may redirect to company ATS after clicking apply
        if "indeed.com" not in self.page.url:
            log.info("external_ats_redirect", url=self.page.url)
            from job_agent.platforms.external_ats import ExternalATSApplicator

            ats = ExternalATSApplicator(self.page, self._get_answerer())
            return ats.apply(job, resume_path, cover_letter_path)

        # Handle Indeed's built-in apply flow
        return self._process_indeed_apply(resume_path)

    def _process_indeed_apply(self, resume_path: str) -> bool:
        """Process Indeed's multi-step apply flow with AI-powered field filling."""
        max_steps = 10
        answerer = self._get_answerer()

        for step in range(max_steps):
            human_delay(1000, 2000)

            # Handle resume upload
            self._upload_resume(resume_path)

            # Extract and fill screening fields if AI is available
            if answerer:
                fields = self._extract_indeed_fields()
                for field in fields:
                    if field.current_value and field.current_value.strip():
                        continue  # Skip pre-filled fields
                    try:
                        answer = answerer.answer_field(field)
                        self._fill_field(field, answer)
                    except Exception as e:
                        log.warning(
                            "screening_fill_error",
                            label=field.label,
                            error=str(e),
                        )

            # Look for continue/submit button
            continue_btn = self.page.locator(SELECTORS.continue_button).first
            if continue_btn.count() > 0:
                text = continue_btn.inner_text().strip().lower()
                if "submit" in text or text == "apply":
                    continue_btn.click()
                    human_delay(2000, 4000)

                    # Check for validation errors
                    errors = self.page.locator(SELECTORS.validation_errors)
                    if errors.count() > 0:
                        log.warning(
                            "indeed_validation_errors",
                            count=errors.count(),
                            step=step,
                        )
                        continue  # Retry this step

                    log.info("indeed_application_submitted")
                    return True
                else:
                    continue_btn.click()
                    human_delay(1500, 3000)
            else:
                break

        log.warning("indeed_apply_max_steps")
        return False

    def _extract_indeed_fields(self) -> list[FormField]:
        """Extract form fields from the current Indeed apply step."""
        fields: list[FormField] = []

        # Try structured field groups first
        group_selectors = [
            SELECTORS.field_group_question_item,
            SELECTORS.field_group_base_page,
            SELECTORS.field_group_fieldset,
            SELECTORS.field_group_testid,
        ]

        for selector in group_selectors:
            groups = self.page.locator(selector).all()
            for group in groups:
                field = self._parse_indeed_field_group(group)
                if field:
                    fields.append(field)

        # Fallback: standalone inputs
        if not fields:
            fields = self._extract_standalone_inputs()

        return fields

    def _parse_indeed_field_group(self, group) -> FormField | None:
        """Parse a single Indeed field group into a FormField."""
        # Find label text
        label_el = group.locator(SELECTORS.field_label).first
        if label_el.count() == 0:
            return None

        try:
            label = label_el.inner_text().strip()
        except Exception:
            return None

        if not label:
            return None

        # Detect field type and build FormField
        # Check for select
        select = group.locator("select").first
        if select.count() > 0:
            options = []
            for opt in group.locator("select option").all():
                text = opt.inner_text().strip()
                val = opt.get_attribute("value") or ""
                if text and val:  # Skip placeholder options with empty value
                    options.append(text)
            selector = self._get_unique_selector(select)
            return FormField(
                label=label,
                field_type="select",
                options=options,
                required=select.get_attribute("required") is not None,
                selector=selector,
            )

        # Check for radio buttons
        radios = group.locator('input[type="radio"]')
        if radios.count() > 0:
            options = []
            for radio in radios.all():
                # Find associated label
                radio_id = radio.get_attribute("id") or ""
                if radio_id:
                    assoc_label = group.locator(f'label[for="{radio_id}"]')
                    if assoc_label.count() > 0:
                        options.append(assoc_label.inner_text().strip())
                        continue
                # Fallback: use value attribute
                val = radio.get_attribute("value") or ""
                if val:
                    options.append(val)
            selector = self._get_unique_selector(group)
            return FormField(
                label=label,
                field_type="radio",
                options=options,
                selector=selector,
            )

        # Check for checkbox
        checkbox = group.locator('input[type="checkbox"]').first
        if checkbox.count() > 0:
            selector = self._get_unique_selector(checkbox)
            return FormField(
                label=label,
                field_type="checkbox",
                selector=selector,
            )

        # Check for textarea
        textarea = group.locator("textarea").first
        if textarea.count() > 0:
            selector = self._get_unique_selector(textarea)
            current = textarea.input_value()
            return FormField(
                label=label,
                field_type="textarea",
                selector=selector,
                current_value=current,
            )

        # Check for text/number input
        text_input = group.locator(
            'input[type="text"], input[type="number"], input[type="tel"], '
            'input[type="email"], input:not([type])'
        ).first
        if text_input.count() > 0:
            input_type = text_input.get_attribute("type") or "text"
            if input_type in ("tel", "email"):
                input_type = "text"
            selector = self._get_unique_selector(text_input)
            current = text_input.input_value()
            return FormField(
                label=label,
                field_type=input_type if input_type == "number" else "text",
                required=text_input.get_attribute("required") is not None,
                selector=selector,
                current_value=current,
            )

        return None

    def _extract_standalone_inputs(self) -> list[FormField]:
        """Fallback: scan visible inputs with labels or aria-labels."""
        fields: list[FormField] = []
        inputs = self.page.locator(
            "input:visible, select:visible, textarea:visible"
        ).all()

        for el in inputs:
            try:
                # Skip file inputs and hidden fields
                input_type = el.get_attribute("type") or ""
                if input_type in ("file", "hidden", "submit", "button"):
                    continue

                # Get label from aria-label, associated label, or placeholder
                label = el.get_attribute("aria-label") or ""
                if not label:
                    el_id = el.get_attribute("id") or ""
                    if el_id:
                        assoc = self.page.locator(f'label[for="{el_id}"]')
                        if assoc.count() > 0:
                            label = assoc.inner_text().strip()
                if not label:
                    label = el.get_attribute("placeholder") or ""
                if not label:
                    continue

                tag = el.evaluate("el => el.tagName.toLowerCase()")
                selector = self._get_unique_selector(el)

                if tag == "select":
                    options = []
                    for opt in el.locator("option").all():
                        text = opt.inner_text().strip()
                        if text:
                            options.append(text)
                    fields.append(
                        FormField(
                            label=label,
                            field_type="select",
                            options=options,
                            selector=selector,
                        )
                    )
                elif tag == "textarea":
                    fields.append(
                        FormField(
                            label=label,
                            field_type="textarea",
                            selector=selector,
                            current_value=el.input_value(),
                        )
                    )
                elif input_type == "checkbox":
                    fields.append(
                        FormField(
                            label=label,
                            field_type="checkbox",
                            selector=selector,
                        )
                    )
                elif input_type == "radio":
                    pass  # Radios handled at group level
                else:
                    ft = "number" if input_type == "number" else "text"
                    fields.append(
                        FormField(
                            label=label,
                            field_type=ft,
                            selector=selector,
                            current_value=el.input_value(),
                        )
                    )
            except Exception:
                continue

        return fields

    @staticmethod
    def _get_unique_selector(el) -> str:
        """Build a CSS selector for an element using id, name, or test attributes."""
        try:
            el_id = el.get_attribute("id")
            if el_id:
                return f"#{el_id}"
            name = el.get_attribute("name")
            tag = el.evaluate("el => el.tagName.toLowerCase()")
            if name:
                return f'{tag}[name="{name}"]'
            data_testid = el.get_attribute("data-testid")
            if data_testid:
                return f'{tag}[data-testid="{data_testid}"]'
            aria_label = el.get_attribute("aria-label")
            if aria_label:
                return f'{tag}[aria-label="{aria_label}"]'
        except Exception:
            pass
        return ""
