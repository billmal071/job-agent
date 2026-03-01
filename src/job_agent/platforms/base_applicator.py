"""Base applicator with template method pattern, retry, and screenshot-on-error."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_delay
from job_agent.config import Settings
from job_agent.platforms.base import JobPosting, safe_goto
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

if TYPE_CHECKING:
    from job_agent.ai.client import AIClient
    from job_agent.ai.screening import FieldAnswer, FormField

log = get_logger(__name__)

# Error patterns that are worth retrying (transient)
_RETRYABLE_PATTERNS = (
    "timeout",
    "net::err_",
    "navigation",
    "target closed",
    "connection refused",
    "econnreset",
)


class BaseApplicator(ABC):
    """Template-method base for all platform applicators.

    Subclasses only need to implement ``_do_apply`` and optionally override
    ``_navigate_to_job`` for platform-specific navigation.
    """

    def __init__(
        self,
        page: Page,
        rate_limiter: RateLimiter,
        settings: Settings,
        ai_client: "AIClient | None" = None,
        profile: dict | None = None,
    ):
        self.page = page
        self.rate_limiter = rate_limiter
        self.settings = settings
        self._ai_client = ai_client
        self._profile = profile

    # ------------------------------------------------------------------
    # Public entry point (template method)
    # ------------------------------------------------------------------

    def apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str = "",
        answers: dict[str, str] | None = None,
    ) -> bool:
        """Apply to *job*. Returns True on success.

        Handles dry-run, rate limiting, retry on transient errors, screenshot
        on failure, and ``rate_limiter.success()`` on success.
        """
        if self.settings.agent.dry_run:
            log.info("dry_run_apply", job=job.title, company=job.company)
            return True

        last_error: Exception | None = None
        for attempt in range(2):  # 1 retry on transient errors
            if not self.rate_limiter.wait():
                log.warning("circuit_breaker_open", job_id=job.external_id)
                return False

            try:
                self._navigate_to_job(job)
                human_delay(2000, 4000)
                success = self._do_apply(job, resume_path, cover_letter_path, answers)
                if success:
                    self.rate_limiter.success()
                return success
            except Exception as e:
                last_error = e
                if attempt == 0 and self._is_retryable_error(e):
                    log.warning(
                        "apply_retrying",
                        job_id=job.external_id,
                        error=str(e),
                        attempt=attempt + 1,
                    )
                    human_delay(2000, 4000)
                    continue
                # Non-retryable or final attempt
                break

        # If we reach here, the apply failed
        log.error("apply_failed", job_id=job.external_id, error=str(last_error))
        self._take_screenshot(f"apply_error_{job.external_id}")
        self.rate_limiter.failure()
        return False

    # ------------------------------------------------------------------
    # Hooks for subclasses
    # ------------------------------------------------------------------

    def _navigate_to_job(self, job: JobPosting) -> None:
        """Navigate to the job page. Override for platform-specific waits."""
        safe_goto(self.page, job.url)
        self.page.wait_for_load_state("domcontentloaded")

    @abstractmethod
    def _do_apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str,
        answers: dict[str, str] | None,
    ) -> bool:
        """Platform-specific application logic. Return True on success."""

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _upload_resume(self, resume_path: str) -> None:
        """Upload a resume via the first visible file input."""
        file_input = self.page.locator('input[type="file"]')
        if file_input.count() > 0 and Path(resume_path).exists():
            file_input.first.set_input_files(resume_path)
            human_delay(1000, 2000)
            log.info("resume_uploaded", path=resume_path)

    def _take_screenshot(self, name: str) -> str:
        """Take a screenshot for debugging."""
        try:
            screenshots_dir = self.settings.data_dir / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            path = screenshots_dir / f"{name}_{int(time.time())}.png"
            self.page.screenshot(path=str(path))
            log.info("screenshot_taken", path=str(path))
            return str(path)
        except Exception as exc:
            log.debug("screenshot_failed", error=str(exc))
            return ""

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """Return True if the error is transient and worth retrying."""
        msg = str(exc).lower()
        return any(p in msg for p in _RETRYABLE_PATTERNS)

    # ------------------------------------------------------------------
    # AI-powered form filling helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_candidate_summary(profile: dict) -> str:
        """Build a candidate summary string from a profile dict."""
        parts: list[str] = []
        if name := profile.get("name"):
            parts.append(f"Target Role: {name}")
        search = profile.get("search", {})
        if exp := search.get("experience_level"):
            parts.append(f"Experience Level: {exp}")
        if locs := search.get("locations"):
            parts.append(f"Locations: {', '.join(locs)}")
        if remote := search.get("remote_preference"):
            parts.append(f"Remote Preference: {remote}")
        skills = profile.get("skills", {})
        if req := skills.get("required"):
            parts.append(f"Required Skills: {', '.join(req)}")
        if pref := skills.get("preferred"):
            parts.append(f"Preferred Skills: {', '.join(pref)}")
        if salary := search.get("salary_minimum"):
            parts.append(f"Minimum Salary: ${salary:,}")
        return "\n".join(parts)

    def _fill_field(self, field: FormField, answer: FieldAnswer) -> None:
        """Dispatch to the appropriate field filler based on type."""
        fillers = {
            "text": self._fill_text_field,
            "number": self._fill_text_field,
            "textarea": self._fill_text_field,
            "select": self._fill_select_field,
            "radio": self._fill_radio_field,
            "checkbox": self._fill_checkbox_field,
        }
        filler = fillers.get(field.field_type, self._fill_text_field)
        try:
            filler(field, answer)
        except Exception as e:
            log.warning(
                "fill_field_error",
                label=field.label,
                field_type=field.field_type,
                error=str(e),
            )

    def _fill_text_field(self, field: FormField, answer: FieldAnswer) -> None:
        """Fill a text/textarea/number input, skipping if pre-filled."""
        el = self.page.locator(field.selector)
        if el.count() == 0:
            return
        current = el.first.input_value()
        if current and current.strip():
            log.debug("field_prefilled", label=field.label, value=current)
            return
        el.first.fill(answer.answer)
        human_delay(300, 600)

    def _fill_select_field(self, field: FormField, answer: FieldAnswer) -> None:
        """Fill a select dropdown, using fuzzy matching if exact match fails."""
        el = self.page.locator(field.selector)
        if el.count() == 0:
            return
        # Try exact match first
        try:
            el.first.select_option(label=answer.answer)
            human_delay(300, 600)
            return
        except Exception:
            pass
        # Fuzzy match
        matched = self._fuzzy_match_option(answer.answer, field.options)
        if matched:
            try:
                el.first.select_option(label=matched)
                human_delay(300, 600)
            except Exception as e:
                log.warning("select_option_failed", label=field.label, error=str(e))

    def _fill_radio_field(self, field: FormField, answer: FieldAnswer) -> None:
        """Click the matching radio button."""
        # Try by value attribute
        container = self.page.locator(field.selector)
        if container.count() == 0:
            return
        # Try matching label text
        labels = container.locator("label").all()
        for label_el in labels:
            text = label_el.inner_text().strip()
            if text.lower() == answer.answer.lower():
                label_el.click()
                human_delay(300, 600)
                return
        # Fuzzy match on labels
        label_texts = [l.inner_text().strip() for l in labels]
        matched = self._fuzzy_match_option(answer.answer, label_texts)
        if matched:
            for label_el in labels:
                if label_el.inner_text().strip() == matched:
                    label_el.click()
                    human_delay(300, 600)
                    return
        # Try by input value
        radio = container.locator(f'input[type="radio"][value="{answer.answer}"]')
        if radio.count() > 0:
            radio.first.click()
            human_delay(300, 600)

    def _fill_checkbox_field(self, field: FormField, answer: FieldAnswer) -> None:
        """Check or uncheck a checkbox based on yes/no answer."""
        el = self.page.locator(field.selector)
        if el.count() == 0:
            return
        should_check = answer.answer.strip().lower() in ("yes", "true", "1", "checked")
        is_checked = el.first.is_checked()
        if should_check and not is_checked:
            el.first.click()
            human_delay(300, 600)
        elif not should_check and is_checked:
            el.first.click()
            human_delay(300, 600)

    @staticmethod
    def _fuzzy_match_option(answer: str, options: list[str]) -> str | None:
        """3-tier fuzzy matching: exact → substring → word overlap."""
        answer_lower = answer.strip().lower()

        # Tier 1: exact (case-insensitive)
        for opt in options:
            if opt.strip().lower() == answer_lower:
                return opt

        # Tier 2: substring match
        for opt in options:
            opt_lower = opt.strip().lower()
            if answer_lower in opt_lower or opt_lower in answer_lower:
                return opt

        # Tier 3: word overlap
        answer_words = set(answer_lower.split())
        best_opt = None
        best_overlap = 0
        for opt in options:
            opt_words = set(opt.strip().lower().split())
            overlap = len(answer_words & opt_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_opt = opt

        if best_overlap > 0:
            return best_opt

        return None
