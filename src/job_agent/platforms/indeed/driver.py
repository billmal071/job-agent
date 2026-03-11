"""Indeed platform driver implementation."""

from __future__ import annotations

from playwright.sync_api import Page

from job_agent.browser.auth import AuthManager
from job_agent.browser.manager import BrowserManager
from job_agent.config import Settings
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting, PlatformDriver
from job_agent.platforms.indeed.discovery import IndeedDiscovery
from job_agent.platforms.indeed.applicator import IndeedApplicator
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class IndeedDriver(PlatformDriver):
    """Indeed job platform driver."""

    platform = Platform.INDEED

    def __init__(self, settings: Settings, browser_manager: BrowserManager):
        self.settings = settings
        self.browser = browser_manager
        platform_cfg = settings.platforms.indeed
        self.rate_limiter = RateLimiter(
            requests_per_minute=platform_cfg.max_requests_per_minute,
            failure_threshold=5,
            cooldown_seconds=platform_cfg.cooldown_minutes * 60,
        )
        self._page: Page | None = None
        self._discovery: IndeedDiscovery | None = None
        self._applicator: IndeedApplicator | None = None

    def login(self, username: str, password: str) -> None:
        context = self.browser.get_context("indeed")
        auth = AuthManager(context)
        self._page = auth.login(Platform.INDEED, username, password)
        self._discovery = IndeedDiscovery(self._page, self.rate_limiter)
        self._applicator = IndeedApplicator(
            self._page, self.rate_limiter, self.settings
        )
        self.browser.save_state("indeed")
        log.info("indeed_driver_ready")

    def _ensure_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Not logged in. Call login() first.")
        return self._page

    def search_jobs(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        experience_level: str = "",
        limit: int = 25,
    ) -> list[JobPosting]:
        self._ensure_page()
        if not self._discovery:
            raise RuntimeError("Not logged in.")
        return self._discovery.search(query=query, location=location, limit=limit)

    def get_job_details(self, job_url: str) -> JobPosting:
        self._ensure_page()
        if not self._discovery:
            raise RuntimeError("Not logged in.")
        return self._discovery.get_details(job_url)

    def apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str = "",
        answers: dict[str, str] | None = None,
    ) -> bool:
        if not self._applicator:
            raise RuntimeError("Not logged in.")
        return self._applicator.apply(job, resume_path)

    def is_already_applied(self, job: JobPosting) -> bool:
        return False  # Indeed doesn't easily show applied status

    def set_ai_context(self, ai_client, profile: dict) -> None:
        """Pass AI client and profile to the applicator for screening questions."""
        if self._applicator:
            self._applicator._ai_client = ai_client
            self._applicator._profile = profile

    def close(self) -> None:
        self.browser.save_state("indeed")
        if self._page and not self._page.is_closed():
            self._page.close()
        self._page = None
        log.info("indeed_driver_closed")
