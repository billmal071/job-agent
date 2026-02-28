"""Playwright browser lifecycle management with persistent contexts."""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Playwright, sync_playwright

from job_agent.browser.stealth import apply_stealth
from job_agent.config import Settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class BrowserManager:
    """Manages Playwright browser instances with persistent state."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._state_dir = Path(settings.browser.state_dir).expanduser()
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """Launch the Playwright instance and browser."""
        self._playwright = sync_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
        ]

        kwargs: dict = {
            "headless": self.settings.browser.headless,
            "args": launch_args,
        }

        if self.settings.browser.proxy:
            kwargs["proxy"] = {"server": self.settings.browser.proxy}

        self._browser = self._playwright.chromium.launch(**kwargs)
        log.info("browser_started", headless=self.settings.browser.headless)

    def get_context(self, name: str = "default") -> BrowserContext:
        """Get or create a named browser context with persistent state."""
        if name in self._contexts:
            return self._contexts[name]

        if not self._browser:
            self.start()

        state_file = self._state_dir / f"{name}_state.json"
        kwargs: dict = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }

        if state_file.exists():
            kwargs["storage_state"] = str(state_file)
            log.info("browser_context_restored", name=name)

        context = self._browser.new_context(**kwargs)  # type: ignore[union-attr]
        apply_stealth(context)

        self._contexts[name] = context
        return context

    def save_state(self, name: str = "default") -> None:
        """Save browser state (cookies, localStorage) for a context."""
        if name in self._contexts:
            state_file = self._state_dir / f"{name}_state.json"
            self._contexts[name].storage_state(path=str(state_file))
            log.info("browser_state_saved", name=name)

    def close_context(self, name: str) -> None:
        """Save state and close a named context."""
        if name in self._contexts:
            self.save_state(name)
            self._contexts[name].close()
            del self._contexts[name]

    def close(self) -> None:
        """Close all contexts and the browser."""
        for name in list(self._contexts):
            self.close_context(name)
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None
        log.info("browser_closed")

    def __enter__(self) -> BrowserManager:
        self.start()
        return self

    def __exit__(self, *args) -> None:
        self.close()
