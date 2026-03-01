"""Platform login flows and session persistence."""

from __future__ import annotations

from playwright.sync_api import BrowserContext, Page

from job_agent.browser.humanizer import human_click, human_delay, human_type
from job_agent.db.models import Platform
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class AuthManager:
    """Handles login flows for job platforms."""

    def __init__(self, context: BrowserContext):
        self.context = context

    def login(self, platform: Platform, username: str, password: str) -> Page:
        """Login to a platform, returning the authenticated page."""
        handlers = {
            Platform.LINKEDIN: self._login_linkedin,
            Platform.INDEED: self._login_indeed,
            Platform.GLASSDOOR: self._login_glassdoor,
            Platform.ZIPRECRUITER: self._login_ziprecruiter,
            Platform.DICE: self._login_dice,
            Platform.WELLFOUND: self._login_wellfound,
        }
        handler = handlers.get(platform)
        if not handler:
            raise ValueError(f"Unsupported platform: {platform}")
        return handler(username, password)

    def is_logged_in(self, platform: Platform, page: Page) -> bool:
        """Check if currently logged into a platform."""
        checks = {
            Platform.LINKEDIN: lambda p: p.locator('[data-control-name="identity_welcome_message"]').count() > 0
            or p.locator(".global-nav__me").count() > 0,
            Platform.INDEED: lambda p: p.locator('[data-gnav-element-name="AccountMenu"]').count() > 0,
            Platform.GLASSDOOR: lambda p: p.locator('[data-test="header-profile"]').count() > 0,
            Platform.ZIPRECRUITER: lambda p: p.locator('.navbar-user-menu, [data-testid="user-menu"]').count() > 0,
            Platform.DICE: lambda p: p.locator('[data-testid="header-user-menu"], .user-menu').count() > 0,
            Platform.WELLFOUND: lambda p: p.locator('[data-test="UserMenu"], .styles_component__NavBarAvatar').count() > 0,
        }
        check = checks.get(platform)
        if not check:
            return False
        try:
            return check(page)
        except Exception:
            return False

    def _login_linkedin(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://www.linkedin.com/login")
        page.wait_for_load_state("networkidle")
        human_delay(1000, 2000)

        human_type(page, "#username", username)
        human_type(page, "#password", password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"]')

        page.wait_for_load_state("networkidle")
        human_delay(2000, 4000)

        # Check for security challenge
        if "checkpoint" in page.url:
            log.warning("linkedin_security_challenge", url=page.url)
            raise RuntimeError(
                "LinkedIn security challenge detected. "
                "Please log in manually once to verify your account."
            )

        if not self.is_logged_in(Platform.LINKEDIN, page):
            log.error("linkedin_login_failed")
            raise RuntimeError("LinkedIn login failed. Check credentials.")

        log.info("linkedin_login_success")
        return page

    def _login_indeed(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://secure.indeed.com/auth")
        page.wait_for_load_state("networkidle")
        human_delay(1000, 2000)

        human_type(page, '[name="__email"]', username)
        human_click(page, '[data-tn-element="auth-page-email-submit"]')
        page.wait_for_load_state("networkidle")
        human_delay(1000, 2000)

        human_type(page, '[name="__password"]', password)
        human_click(page, '[data-tn-element="auth-page-sign-in-submit"]')
        page.wait_for_load_state("networkidle")
        human_delay(2000, 4000)

        log.info("indeed_login_complete")
        return page

    def _login_glassdoor(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://www.glassdoor.com/profile/login_input.htm")
        page.wait_for_load_state("networkidle")
        human_delay(1000, 2000)

        human_type(page, '[name="username"]', username)
        human_type(page, '[name="password"]', password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"]')

        page.wait_for_load_state("networkidle")
        human_delay(2000, 4000)

        log.info("glassdoor_login_complete")
        return page

    def _login_ziprecruiter(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://www.ziprecruiter.com/authn/login")
        page.wait_for_load_state("networkidle")
        human_delay(1000, 2000)

        human_type(page, '[name="email"], #email', username)
        human_type(page, '[name="password"], #password', password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"]')

        page.wait_for_load_state("networkidle")
        human_delay(2000, 4000)

        log.info("ziprecruiter_login_complete")
        return page

    def _login_dice(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://www.dice.com/dashboard/login")
        page.wait_for_load_state("networkidle")
        human_delay(1000, 2000)

        human_type(page, '[name="email"], #email', username)
        human_type(page, '[name="password"], #password', password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"], button:has-text("Sign In")')

        page.wait_for_load_state("networkidle")
        human_delay(2000, 4000)

        log.info("dice_login_complete")
        return page

    def _login_wellfound(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://wellfound.com/login")
        page.wait_for_load_state("networkidle")
        human_delay(1000, 2000)

        human_type(page, '[name="email"], #user_email', username)
        human_type(page, '[name="password"], #user_password', password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"], button:has-text("Log in")')

        page.wait_for_load_state("networkidle")
        human_delay(2000, 4000)

        log.info("wellfound_login_complete")
        return page
