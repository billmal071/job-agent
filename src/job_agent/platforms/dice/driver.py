"""Dice platform driver implementation."""

from __future__ import annotations

from playwright.sync_api import Page

from job_agent.browser.auth import AuthManager
from job_agent.browser.manager import BrowserManager
from job_agent.config import Settings
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting, PlatformDriver
from job_agent.platforms.dice.applicator import DiceApplicator
from job_agent.platforms.dice.discovery import DiceDiscovery
from job_agent.utils.logging import get_logger
from job_agent.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


class DiceDriver(PlatformDriver):
    """Dice job platform driver."""

    platform = Platform.DICE

    def __init__(self, settings: Settings, browser_manager: BrowserManager):
        self.settings = settings
        self.browser = browser_manager
        platform_cfg = settings.platforms.dice
        self.rate_limiter = RateLimiter(
            requests_per_minute=platform_cfg.max_requests_per_minute,
            failure_threshold=5,
            cooldown_seconds=platform_cfg.cooldown_minutes * 60,
        )
        self._page: Page | None = None
        self._discovery: DiceDiscovery | None = None
        self._applicator: DiceApplicator | None = None

    def login(self, username: str, password: str) -> None:
        context = self.browser.get_context("dice")
        auth = AuthManager(context)
        self._page = auth.login(Platform.DICE, username, password)
        self._discovery = DiceDiscovery(self._page, self.rate_limiter)
        self._applicator = DiceApplicator(
            self._page, self.rate_limiter, self.settings
        )
        self.browser.save_state("dice")
        log.info("dice_driver_ready")

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
        return self._discovery.search(
            query=query, location=location, remote=remote,
            experience_level=experience_level, limit=limit,
        )

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
        return False

    def close(self) -> None:
        self.browser.save_state("dice")
        if self._page and not self._page.is_closed():
            self._page.close()
        self._page = None
        log.info("dice_driver_closed")
