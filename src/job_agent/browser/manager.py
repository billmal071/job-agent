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
        self._camoufox_ctx = None  # Camoufox context manager
        self._contexts: dict[str, BrowserContext] = {}
        self._state_dir = Path(settings.browser.state_dir).expanduser()
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def start(self) -> None:
        """Launch the browser instance."""
        if self.settings.browser.use_camoufox:
            self._start_camoufox()
        else:
            self._start_playwright()

    def _start_camoufox(self) -> None:
        """Launch Camoufox anti-detection browser."""
        from camoufox.sync_api import Camoufox

        kwargs: dict = {
            "headless": self.settings.browser.headless,
            "humanize": True,
        }
        if self.settings.browser.proxy:
            kwargs["proxy"] = {"server": self.settings.browser.proxy}

        self._camoufox_ctx = Camoufox(**kwargs)
        self._browser = self._camoufox_ctx.__enter__()
        log.info("camoufox_started", headless=self.settings.browser.headless)

    def _start_playwright(self) -> None:
        """Launch standard Playwright Chromium browser."""
        self._playwright = sync_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
        if not self.settings.browser.headless:
            launch_args.append("--start-maximized")

        kwargs: dict = {
            "headless": self.settings.browser.headless,
            "args": launch_args,
            "channel": "chrome",
        }

        if self.settings.browser.proxy:
            kwargs["proxy"] = {"server": self.settings.browser.proxy}

        try:
            self._browser = self._playwright.chromium.launch(**kwargs)
        except Exception as e:
            log.warning("chrome_launch_failed_trying_chromium", error=str(e))
            kwargs.pop("channel", None)
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
            "viewport": {
                "width": self.settings.browser.viewport_width,
                "height": self.settings.browser.viewport_height,
            },
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }
        # Camoufox manages its own fingerprint — don't override user_agent
        if not self.settings.browser.use_camoufox:
            kwargs["user_agent"] = (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
            )

        if state_file.exists():
            kwargs["storage_state"] = str(state_file)
            log.info("browser_context_restored", name=name)

        context = self._browser.new_context(**kwargs)  # type: ignore[union-attr]
        if not self.settings.browser.use_camoufox:
            apply_stealth(context)

        self._contexts[name] = context
        return context

    def save_state(self, name: str = "default") -> None:
        """Save browser state (cookies, localStorage) for a context."""
        if name in self._contexts:
            state_file = self._state_dir / f"{name}_state.json"
            try:
                self._contexts[name].storage_state(path=str(state_file))
                log.info("browser_state_saved", name=name)
            except Exception as e:
                log.error("browser_state_save_failed", name=name, error=str(e))

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
        if self._camoufox_ctx:
            self._camoufox_ctx.__exit__(None, None, None)
            self._camoufox_ctx = None
            self._browser = None
        elif self._browser:
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
