"""External ATS applicator for Greenhouse, Lever, Workday, Ashby, and generic forms.

When Glassdoor/Indeed redirects to a company's ATS, this module detects
which ATS it is and walks through the application form using AI-powered
field filling.  Also handles email-only apply pages by sending an email
with resume and cover letter attached.
"""

from __future__ import annotations

import re
import smtplib
from dataclasses import dataclass
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from playwright.sync_api import Page

from job_agent.ai.screening import FormField, ScreeningAnswerer
from job_agent.browser.humanizer import human_delay
from job_agent.platforms.base import JobPosting
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# ATS detection
# ---------------------------------------------------------------------------


@dataclass
class ATSInfo:
    """Identified ATS platform."""

    name: str  # greenhouse, lever, ashby, workday, generic
    base_domain: str


_ATS_PATTERNS: list[tuple[str, str]] = [
    (
        r"boards\.greenhouse\.io|job-boards\.greenhouse\.io|greenhouse\.io/embed",
        "greenhouse",
    ),
    (r"jobs\.lever\.co|lever\.co/.*apply", "lever"),
    (r"jobs\.ashbyhq\.com|ashbyhq\.com", "ashby"),
    (r"myworkday(jobs)?\.com|workday\.com", "workday"),
    (r"jobvite\.com", "jobvite"),
    (r"smartrecruiters\.com", "smartrecruiters"),
    (r"breezy\.hr", "breezy"),
    (r"recruitee\.com", "recruitee"),
    (r"icims\.com", "icims"),
    (r"jazz\.co|applytojob\.com", "jazzhr"),
    (r"bamboohr\.com", "bamboohr"),
    (r"ultipro\.com|ukg\.com", "ukg"),
    (r"taleo\.net", "taleo"),
]


def detect_ats(url: str) -> ATSInfo | None:
    """Detect which ATS a URL belongs to."""
    for pattern, name in _ATS_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return ATSInfo(name=name, base_domain=pattern)
    return None


# ---------------------------------------------------------------------------
# External ATS Applicator
# ---------------------------------------------------------------------------


class ExternalATSApplicator:
    """Handles application forms on external ATS platforms.

    Uses AI-powered field detection and filling that adapts to any form
    structure. Has ATS-specific optimisations for Greenhouse, Lever, and
    Ashby which have predictable HTML structures.
    """

    MAX_STEPS = 12

    def __init__(
        self,
        page: Page,
        answerer: ScreeningAnswerer | None,
    ):
        self.page = page
        self.answerer = answerer

    def apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str = "",
    ) -> bool:
        """Attempt to fill and submit the external ATS application."""
        url = self.page.url
        # If still on the job board (not redirected), skip
        if any(
            domain in url for domain in ("indeed.com", "glassdoor.com", "linkedin.com")
        ):
            log.warning("still_on_job_board", url=url)
            return False

        # Check for email-only apply page first
        email_addr = self._detect_email_apply()
        if email_addr:
            log.info("email_apply_detected", email=email_addr, job=job.title)
            return self._send_email_application(
                email_addr, job, resume_path, cover_letter_path
            )

        ats = detect_ats(url)
        ats_name = ats.name if ats else "generic"
        log.info("external_ats_apply", ats=ats_name, url=url)

        try:
            if ats_name == "greenhouse":
                return self._apply_greenhouse(job, resume_path, cover_letter_path)
            elif ats_name == "lever":
                return self._apply_lever(job, resume_path, cover_letter_path)
            elif ats_name == "ashby":
                return self._apply_ashby(job, resume_path, cover_letter_path)
            else:
                return self._apply_generic(job, resume_path, cover_letter_path)
        except Exception as e:
            log.error("external_ats_error", ats=ats_name, error=str(e))
            return False

    # ------------------------------------------------------------------
    # Email-only apply detection & sending
    # ------------------------------------------------------------------

    def _detect_email_apply(self) -> str | None:
        """Detect if the page is an email-only apply page.

        Returns the email address if found, None otherwise.
        """
        # Check for mailto: links
        try:
            mailto_links = self.page.locator('a[href^="mailto:"]').all()
            for link in mailto_links:
                href = link.get_attribute("href") or ""
                match = re.match(r"mailto:([^\?]+)", href)
                if match:
                    email = match.group(1).strip()
                    # Verify it looks like a job/career email
                    log.info("mailto_link_found", email=email)
                    return email
        except Exception as e:
            log.debug("mailto_detection_failed", error=str(e))

        # Check page text for "send/email your resume to ..." patterns
        try:
            body = self.page.locator("body").inner_text()
            patterns = [
                r"(?:send|email|submit|forward)\s+(?:your\s+)?(?:resume|cv|application)\s+(?:to\s+)?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"(?:apply|applications?)\s+(?:via|by|through)\s+(?:email\s+)?(?:at\s+)?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                r"(?:contact|reach out)\s+(?:us\s+)?(?:at\s+)?([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
            ]
            for pattern in patterns:
                match = re.search(pattern, body, re.IGNORECASE)
                if match:
                    email = match.group(1).strip()
                    log.info("email_in_text_found", email=email)
                    return email
        except Exception as e:
            log.debug("email_text_detection_failed", error=str(e))

        # Check if page has no form at all but has an email address
        try:
            has_form = (
                self.page.locator(
                    "form, input[type='file'], input[type='text']"
                ).count()
                > 0
            )
            if not has_form:
                # No form — look for any email address on the page
                body = self.page.locator("body").inner_text()
                emails = re.findall(
                    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", body
                )
                # Filter out common non-apply emails
                skip = {
                    "privacy@",
                    "support@",
                    "info@",
                    "help@",
                    "noreply@",
                    "no-reply@",
                }
                for email in emails:
                    if not any(email.lower().startswith(s) for s in skip):
                        log.info("email_no_form_found", email=email)
                        return email
        except Exception as e:
            log.debug("email_no_form_detection_failed", error=str(e))

        return None

    def _send_email_application(
        self,
        to_email: str,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str = "",
    ) -> bool:
        """Send an application email with resume and cover letter attached."""
        from job_agent.config import Settings

        settings = Settings()
        if not settings.smtp_user or not settings.smtp_password:
            log.warning("smtp_not_configured")
            return False

        msg = MIMEMultipart()
        msg["From"] = settings.smtp_user
        msg["To"] = to_email
        msg["Subject"] = f"Application for {job.title}"

        # Body text — use cover letter content if available, otherwise generic
        body_text = ""
        if cover_letter_path and Path(cover_letter_path).exists():
            body_text = Path(cover_letter_path).read_text()
        else:
            body_text = (
                f"Dear Hiring Manager,\n\n"
                f"I am writing to express my interest in the {job.title} position "
                f"at {job.company}. Please find my resume attached.\n\n"
                f"Thank you for your consideration.\n\n"
                f"Best regards"
            )
        msg.attach(MIMEText(body_text, "plain"))

        # Attach resume
        if resume_path and Path(resume_path).exists():
            resume = Path(resume_path)
            with open(resume, "rb") as f:
                att = MIMEApplication(f.read(), _subtype="pdf")
                att.add_header(
                    "Content-Disposition", "attachment", filename=resume.name
                )
                msg.attach(att)

        # Attach cover letter as file too if it exists
        if cover_letter_path and Path(cover_letter_path).exists():
            cl = Path(cover_letter_path)
            with open(cl, "rb") as f:
                att = MIMEApplication(f.read(), _subtype="plain")
                att.add_header("Content-Disposition", "attachment", filename=cl.name)
                msg.attach(att)

        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
            log.info("email_application_sent", to=to_email, job=job.title)
            return True
        except Exception as e:
            log.error("email_application_failed", to=to_email, error=str(e))
            return False

    # ------------------------------------------------------------------
    # Greenhouse
    # ------------------------------------------------------------------

    def _apply_greenhouse(
        self, job: JobPosting, resume_path: str, cover_letter_path: str
    ) -> bool:
        """Greenhouse uses a single-page form with #application_form."""
        human_delay(2000, 3000)

        # Upload resume
        self._upload_file(
            resume_path,
            'input[type="file"][name*="resume"], input[data-field="resume"]',
        )
        if not resume_path:
            # Try generic file input
            self._upload_file_first(resume_path)

        # Upload cover letter if available
        if cover_letter_path:
            self._upload_file(
                cover_letter_path,
                'input[type="file"][name*="cover_letter"], input[data-field="cover_letter"]',
            )

        # Fill all form fields
        self._fill_all_fields()

        # Submit
        return self._click_submit(
            '#submit_app, button[type="submit"], '
            'input[type="submit"], button:has-text("Submit Application")'
        )

    # ------------------------------------------------------------------
    # Lever
    # ------------------------------------------------------------------

    def _apply_lever(
        self, job: JobPosting, resume_path: str, cover_letter_path: str
    ) -> bool:
        """Lever has a job page + separate apply form."""
        human_delay(2000, 3000)

        # Lever job pages require clicking "Apply for this job" to get to the form
        apply_btn = self.page.locator(
            'a.postings-btn:has-text("Apply"), '
            'a:has-text("Apply for this job"), '
            'a:has-text("Apply now"), '
            ".posting-btn-submit a"
        ).first
        if apply_btn.count() > 0:
            log.info("lever_clicking_apply_button")
            apply_btn.click()
            human_delay(3000, 5000)

        # Upload resume
        self._upload_file(
            resume_path,
            '.application-upload input[type="file"], '
            'input[name="resume"], '
            'input[type="file"]',
        )

        # Fill form fields
        self._fill_all_fields()

        # Check for hCaptcha — try to solve by clicking checkbox in iframe
        hcaptcha = self.page.locator('.h-captcha, iframe[src*="hcaptcha"]').first
        if hcaptcha.count() > 0:
            log.warning("lever_hcaptcha_detected")
            try:
                # Scroll hCaptcha into view
                hcaptcha.evaluate(
                    "el => el.scrollIntoView({behavior: 'smooth', block: 'center'})"
                )
                human_delay(1000, 2000)
                # Use frame_locator to access hCaptcha iframe content
                captcha_frame = self.page.frame_locator('iframe[src*="hcaptcha"]')
                checkbox = captcha_frame.locator("#checkbox")
                if checkbox.count() > 0:
                    checkbox.click()
                    log.info("hcaptcha_checkbox_clicked")
                    human_delay(5000, 8000)
                else:
                    log.warning("hcaptcha_no_checkbox_found")
            except Exception as e:
                log.debug("hcaptcha_click_failed", error=str(e))

        # Submit — Lever's button is type="button" with data-qa="btn-submit"
        # Note: #btn-submit can match hCaptcha hidden button, so use data-qa
        return self._click_submit(
            'button[data-qa="btn-submit"], '
            "button.template-btn-submit, "
            'button:has-text("Submit application"), '
            'button:has-text("Submit"), '
            'button[type="submit"]:visible, '
            'a:has-text("Submit application"), '
            '.postings-btn[type="submit"]'
        )

    # ------------------------------------------------------------------
    # Ashby
    # ------------------------------------------------------------------

    def _apply_ashby(
        self, job: JobPosting, resume_path: str, cover_letter_path: str
    ) -> bool:
        """Ashby has a modern React-based form."""
        human_delay(2000, 3000)

        # Upload resume
        self._upload_file(
            resume_path,
            'input[type="file"][accept*="pdf"], input[type="file"]',
        )

        # Fill form fields
        self._fill_all_fields()

        # Submit
        return self._click_submit(
            'button[type="submit"], '
            'button:has-text("Submit Application"), '
            'button:has-text("Submit")'
        )

    # ------------------------------------------------------------------
    # Generic ATS
    # ------------------------------------------------------------------

    def _apply_generic(
        self, job: JobPosting, resume_path: str, cover_letter_path: str
    ) -> bool:
        """Best-effort application for unknown ATS platforms.

        Walks through multi-step forms, uploading resume and filling
        fields on each page.
        """
        human_delay(2000, 3000)

        # Detect CAPTCHA or login-required pages early
        body_text = self.page.locator("body").inner_text().lower()
        if any(
            kw in body_text
            for kw in ("captcha", "type the above code", "verify you are human")
        ):
            log.warning("generic_ats_captcha_detected")
            return False
        if any(
            kw in body_text
            for kw in ("create an account", "sign up to apply", "register to apply")
        ):
            log.warning("generic_ats_requires_account")
            return False

        prev_url = self.page.url
        stale_count = 0

        for step in range(self.MAX_STEPS):
            # Detect stuck loops — if URL hasn't changed for 3 steps, bail
            current_url = self.page.url
            if current_url == prev_url:
                stale_count += 1
                if stale_count >= 3:
                    log.warning("generic_ats_stuck_loop", url=current_url)
                    break
            else:
                stale_count = 0
                prev_url = current_url

            # Upload resume on first step or when file input appears
            if step == 0:
                self._upload_file_first(resume_path)

                # Upload cover letter if there's a second file input
                if cover_letter_path:
                    file_inputs = self.page.locator('input[type="file"]').all()
                    if len(file_inputs) > 1:
                        try:
                            if Path(cover_letter_path).exists():
                                file_inputs[1].set_input_files(cover_letter_path)
                                human_delay(500, 1000)
                        except Exception as e:
                            log.debug("cover_letter_upload_failed", error=str(e))

            # Fill form fields
            self._fill_all_fields()
            human_delay(1000, 2000)

            # Look for submit or continue
            submit = self.page.locator(
                'button[data-qa="btn-submit"], '
                "button.template-btn-submit, "
                'button[type="submit"]:visible:has-text("Submit"), '
                'button:has-text("Submit Application"), '
                'button:has-text("Submit application"), '
                'button[aria-label*="Submit"], '
                'input[type="submit"][value*="Submit"], '
                'input[type="submit"][value*="Apply"]'
            ).first
            if submit.count() > 0:
                try:
                    submit.evaluate(
                        "el => el.scrollIntoView({behavior: 'smooth', block: 'center'})"
                    )
                    human_delay(500, 1000)
                except Exception as e:
                    log.debug("submit_scroll_failed", error=str(e))
                try:
                    submit.click(force=True)
                except Exception:
                    try:
                        submit.evaluate("el => el.click()")
                    except Exception as e:
                        log.debug("submit_click_failed", error=str(e))
                human_delay(3000, 5000)
                # Check for success indicators
                if self._check_success():
                    log.info("generic_ats_submitted")
                    return True
                # Might still be on the form (validation error), continue
                continue

            # Next/Continue button
            next_btn = self.page.locator(
                'button:has-text("Next"), '
                'button:has-text("Continue"), '
                'button:has-text("Save and Continue"), '
                'button[type="submit"]:not(:has-text("Submit"))'
            ).first
            if next_btn.count() > 0 and next_btn.is_visible():
                next_btn.click(force=True)
                human_delay(2000, 3000)
                continue

            # No buttons found — check if we already submitted
            if self._check_success():
                return True

            break

        log.warning("generic_ats_max_steps")
        return False

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _upload_file(self, file_path: str, selector: str) -> bool:
        """Upload a file to a specific input."""
        if not file_path:
            return False
        from pathlib import Path

        if not Path(file_path).exists():
            return False

        try:
            el = self.page.locator(selector).first
            if el.count() > 0:
                el.set_input_files(file_path)
                human_delay(1000, 2000)
                log.info("ats_file_uploaded", path=file_path)
                return True
        except Exception as e:
            log.debug("ats_file_upload_error", error=str(e))
        return False

    def _upload_file_first(self, file_path: str) -> bool:
        """Upload to the first file input on the page."""
        return self._upload_file(file_path, 'input[type="file"]')

    def _fill_all_fields(self) -> None:
        """Extract and AI-fill all visible form fields."""
        if not self.answerer:
            return

        fields = self._extract_fields()
        for field in fields:
            if field.current_value and field.current_value.strip():
                continue
            try:
                answer = self.answerer.answer_field(field)
                self._fill_field(field, answer)
            except Exception as e:
                log.debug("ats_field_fill_error", label=field.label, error=str(e))

    def _extract_fields(self) -> list[FormField]:
        """Extract form fields from the current page using multiple strategies."""
        fields: list[FormField] = []

        # Strategy 1: fieldsets and form groups (most ATS use these)
        group_selectors = [
            ".field",
            ".form-field",
            ".form-group",
            ".form__field",
            "[data-field]",
            ".application-field",
            ".question",
            "fieldset",
            ".field-group",
            ".input-wrapper",
            # Greenhouse specific
            "#application_form .field",
            # Lever specific
            ".application-question",
            # Ashby specific
            "[class*='FormField']",
        ]

        for selector in group_selectors:
            groups = self.page.locator(selector).all()
            for group in groups:
                field = self._parse_field_group(group)
                if field:
                    fields.append(field)

        # Strategy 2: fallback to standalone visible inputs
        if not fields:
            fields = self._extract_standalone_fields()

        # Deduplicate by selector
        seen: set[str] = set()
        unique: list[FormField] = []
        for f in fields:
            if f.selector and f.selector not in seen:
                seen.add(f.selector)
                unique.append(f)
            elif not f.selector:
                unique.append(f)

        return unique

    def _parse_field_group(self, group) -> FormField | None:
        """Parse a form field group into a FormField."""
        # Find label
        label_el = group.locator(
            "label, legend, .field-label, .label, [class*='label']"
        ).first
        if label_el.count() == 0:
            return None

        try:
            label = label_el.inner_text().strip()
        except Exception:
            return None
        if not label or len(label) > 200:
            return None

        # Select
        select = group.locator("select").first
        if select.count() > 0:
            options = []
            for opt in group.locator("select option").all():
                text = opt.inner_text().strip()
                val = opt.get_attribute("value") or ""
                if text and val:
                    options.append(text)
            return FormField(
                label=label,
                field_type="select",
                options=options,
                required=select.get_attribute("required") is not None,
                selector=self._unique_selector(select),
            )

        # Radio
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
            return FormField(
                label=label,
                field_type="radio",
                options=options,
                selector=self._unique_selector(group),
            )

        # Checkbox
        checkbox = group.locator('input[type="checkbox"]').first
        if checkbox.count() > 0:
            return FormField(
                label=label,
                field_type="checkbox",
                selector=self._unique_selector(checkbox),
            )

        # Textarea
        textarea = group.locator("textarea").first
        if textarea.count() > 0:
            return FormField(
                label=label,
                field_type="textarea",
                selector=self._unique_selector(textarea),
                current_value=textarea.input_value(),
            )

        # Text/number input
        text_input = group.locator(
            'input[type="text"], input[type="number"], input[type="tel"], '
            'input[type="email"], input[type="url"], input:not([type])'
        ).first
        if text_input.count() > 0:
            input_type = text_input.get_attribute("type") or "text"
            mapped = "number" if input_type == "number" else "text"
            return FormField(
                label=label,
                field_type=mapped,
                required=text_input.get_attribute("required") is not None,
                selector=self._unique_selector(text_input),
                current_value=text_input.input_value(),
            )

        return None

    def _extract_standalone_fields(self) -> list[FormField]:
        """Fallback: scan all visible inputs."""
        fields: list[FormField] = []
        inputs = self.page.locator(
            "input:visible, select:visible, textarea:visible"
        ).all()

        for el in inputs:
            try:
                input_type = el.get_attribute("type") or ""
                if input_type in ("file", "hidden", "submit", "button"):
                    continue

                label = (
                    el.get_attribute("aria-label")
                    or self._label_for(el)
                    or el.get_attribute("placeholder")
                    or ""
                )
                if not label:
                    continue

                tag = el.evaluate("el => el.tagName.toLowerCase()")
                selector = self._unique_selector(el)

                if tag == "select":
                    options = [
                        o.inner_text().strip()
                        for o in el.locator("option").all()
                        if o.inner_text().strip()
                    ]
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
                        FormField(label=label, field_type="checkbox", selector=selector)
                    )
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
            except Exception as e:
                log.debug("standalone_field_extract_failed", error=str(e))
                continue

        return fields

    def _label_for(self, el) -> str:
        """Find the label text associated with an element."""
        try:
            el_id = el.get_attribute("id") or ""
            if el_id:
                assoc = self.page.locator(f'label[for="{el_id}"]')
                if assoc.count() > 0:
                    return assoc.inner_text().strip()
        except Exception as e:
            log.debug("label_lookup_failed", error=str(e))
        return ""

    def _fill_field(self, field: FormField, answer) -> None:
        """Fill a single field with the AI-generated answer."""
        if not field.selector:
            return

        el = self.page.locator(field.selector).first
        if el.count() == 0:
            return

        try:
            if field.field_type == "select":
                try:
                    el.select_option(label=answer.answer)
                except Exception:
                    # Fuzzy match
                    for opt in field.options:
                        if (
                            answer.answer.lower() in opt.lower()
                            or opt.lower() in answer.answer.lower()
                        ):
                            el.select_option(label=opt)
                            break
            elif field.field_type == "radio":
                container = self.page.locator(field.selector)
                labels = container.locator("label").all()
                for lbl in labels:
                    if answer.answer.lower() in lbl.inner_text().strip().lower():
                        lbl.click()
                        break
            elif field.field_type == "checkbox":
                should = answer.answer.strip().lower() in (
                    "yes",
                    "true",
                    "1",
                    "checked",
                )
                if should and not el.is_checked():
                    el.click()
                elif not should and el.is_checked():
                    el.click()
            else:
                # text, textarea, number
                current = el.input_value()
                if not current or not current.strip():
                    el.fill(answer.answer)
        except Exception as e:
            log.debug("ats_fill_error", label=field.label, error=str(e))

        human_delay(200, 500)

    def _click_submit(self, selector: str) -> bool:
        """Click a submit button and check for success."""
        btn = self.page.locator(selector).first
        if btn.count() == 0:
            # Debug: list all buttons on the page
            all_btns = self.page.locator("button, input[type='submit']").all()
            for b in all_btns[:10]:
                try:
                    txt = b.inner_text().strip()[:50]
                    tag = b.evaluate("el => el.outerHTML.substring(0, 120)")
                    log.warning("ats_found_button", text=txt, html=tag)
                except Exception:
                    pass
            log.warning("ats_no_submit_button", selector=selector)
            return False

        try:
            btn_html = btn.evaluate("el => el.outerHTML.substring(0, 150)")
            log.info("ats_clicking_submit", html=btn_html)
        except Exception as e:
            log.debug("submit_html_read_failed", error=str(e))

        # Scroll into view using JS (handles nested scrollable containers)
        try:
            btn.evaluate(
                "el => el.scrollIntoView({behavior: 'smooth', block: 'center'})"
            )
            human_delay(1000, 2000)
        except Exception as e:
            log.debug("submit_scroll_failed", error=str(e))
        try:
            btn.click(force=True)
        except Exception:
            # Last resort: JS click
            try:
                btn.evaluate("el => el.click()")
            except Exception as e:
                log.error("ats_submit_click_failed", error=str(e))
                return False
        human_delay(3000, 5000)

        success = self._check_success()
        if not success:
            log.warning("ats_submit_no_success_detected", url=self.page.url[:100])
        return success

    def _check_success(self) -> bool:
        """Heuristic check for application success."""
        # Check for common success text
        body = self.page.locator("body").inner_text().lower()
        success_phrases = [
            "application submitted",
            "thank you for applying",
            "thanks for applying",
            "application received",
            "application has been submitted",
            "successfully submitted",
            "we've received your application",
            "your application has been received",
            "thank you for your interest",
            "you have successfully applied",
        ]
        for phrase in success_phrases:
            if phrase in body:
                log.info("ats_success_detected", phrase=phrase)
                return True

        # Check for success URL patterns
        url = self.page.url.lower()
        if any(p in url for p in ("confirmation", "thank-you", "success", "applied")):
            log.info("ats_success_url", url=url)
            return True

        return False

    @staticmethod
    def _unique_selector(el) -> str:
        """Build a CSS selector for an element."""
        try:
            el_id = el.get_attribute("id")
            if el_id:
                # Escape special CSS characters in IDs (e.g. React aria IDs with colons)
                escaped = re.sub(r"([:\[\]\.#>+~,\(\)])", r"\\\1", el_id)
                return f"#{escaped}"
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
        except Exception as e:
            log.debug("unique_selector_failed", error=str(e))
        return ""
