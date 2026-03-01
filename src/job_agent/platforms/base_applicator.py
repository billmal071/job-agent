"""Base applicator with template method pattern, retry, and screenshot-on-error."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path

from playwright.sync_api import Page

from job_agent.browser.humanizer import human_delay
from job_agent.config import Settings
from job_agent.platforms.base import JobPosting, safe_goto
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

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

    def __init__(self, page: Page, rate_limiter: RateLimiter, settings: Settings):
        self.page = page
        self.rate_limiter = rate_limiter
        self.settings = settings

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
