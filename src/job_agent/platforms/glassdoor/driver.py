"""Glassdoor platform driver implementation."""

from __future__ import annotations

from playwright.sync_api import Page

from job_agent.browser.auth import AuthManager
from job_agent.browser.manager import BrowserManager
from job_agent.config import Settings
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting, PlatformDriver
from job_agent.platforms.glassdoor.discovery import GlassdoorDiscovery
from job_agent.platforms.glassdoor.applicator import GlassdoorApplicator
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class GlassdoorDriver(PlatformDriver):
    """Glassdoor job platform driver."""

    platform = Platform.GLASSDOOR

    def __init__(self, settings: Settings, browser_manager: BrowserManager):
        self.settings = settings
        self.browser = browser_manager
        platform_cfg = settings.platforms.glassdoor
        self.rate_limiter = RateLimiter(
            requests_per_minute=platform_cfg.max_requests_per_minute,
            failure_threshold=5,
            cooldown_seconds=platform_cfg.cooldown_minutes * 60,
        )
        self._page: Page | None = None

    def login(self, username: str, password: str) -> None:
        context = self.browser.get_context("glassdoor")
        auth = AuthManager(context)
        self._page = auth.login(Platform.GLASSDOOR, username, password)
        self.browser.save_state("glassdoor")
        log.info("glassdoor_driver_ready")

    def _ensure_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Not logged in.")
        return self._page

    def search_jobs(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        experience_level: str = "",
        limit: int = 25,
    ) -> list[JobPosting]:
        page = self._ensure_page()
        discovery = GlassdoorDiscovery(page, self.rate_limiter)
        return discovery.search(query=query, location=location, limit=limit)

    def get_job_details(self, job_url: str) -> JobPosting:
        page = self._ensure_page()
        discovery = GlassdoorDiscovery(page, self.rate_limiter)
        return discovery.get_details(job_url)

    def apply(
        self,
        job: JobPosting,
        resume_path: str,
        cover_letter_path: str = "",
        answers: dict[str, str] | None = None,
    ) -> bool:
        page = self._ensure_page()
        applicator = GlassdoorApplicator(page, self.rate_limiter, self.settings)
        return applicator.apply(job, resume_path)

    def is_already_applied(self, job: JobPosting) -> bool:
        return False

    def close(self) -> None:
        self.browser.save_state("glassdoor")
        if self._page and not self._page.is_closed():
            self._page.close()
        self._page = None
        log.info("glassdoor_driver_closed")
