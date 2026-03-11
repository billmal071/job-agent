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
            Platform.LINKEDIN: lambda p: (
                p.locator(".global-nav__me").count() > 0
                or p.locator('[data-control-name="identity_welcome_message"]').count()
                > 0
                or p.locator(".feed-identity-module").count() > 0
                or p.locator('nav[aria-label="Primary"]').count() > 0
            ),
            Platform.INDEED: lambda p: p.locator(
                '[data-gnav-element-name="AccountMenu"]'
            ).count()
            > 0,
            Platform.GLASSDOOR: lambda p: p.locator(
                '[data-test="header-profile"]'
            ).count()
            > 0,
            Platform.ZIPRECRUITER: lambda p: p.locator(
                '.navbar-user-menu, [data-testid="user-menu"]'
            ).count()
            > 0,
            Platform.DICE: lambda p: p.locator(
                '[data-testid="header-user-menu"], .user-menu'
            ).count()
            > 0,
            Platform.WELLFOUND: lambda p: p.locator(
                '[data-test="UserMenu"], .styles_component__NavBarAvatar'
            ).count()
            > 0,
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
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        human_delay(2000, 3000)

        # Already logged in from saved session
        if self.is_logged_in(Platform.LINKEDIN, page) or (
            "login" not in page.url and "checkpoint" not in page.url
        ):
            log.info("linkedin_session_restored")
            return page

        # Not logged in — go to login page
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        human_delay(1000, 2000)

        human_type(page, "#username", username)
        human_type(page, "#password", password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"]')

        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        # Check for security challenge — wait for manual resolution
        if "checkpoint" in page.url or not self.is_logged_in(Platform.LINKEDIN, page):
            log.warning(
                "linkedin_manual_intervention",
                url=page.url,
                message="Waiting up to 120s for manual login/verification...",
            )
            # Wait until the page leaves login/checkpoint URLs
            for _ in range(60):
                human_delay(2000, 2500)
                current = page.url
                if "checkpoint" not in current and "login" not in current:
                    break
            human_delay(3000, 5000)

        if not self.is_logged_in(Platform.LINKEDIN, page):
            # Fallback: if we're past login/checkpoint, trust it
            current = page.url
            if "checkpoint" not in current and "login" not in current:
                log.info("linkedin_login_success_fallback", url=current)
            else:
                log.error("linkedin_login_failed", url=current)
                raise RuntimeError("LinkedIn login failed. Check credentials.")

        log.info("linkedin_login_success")
        return page

    def _wait_for_oauth_login(
        self, page: Page, platform: str, success_url_part: str
    ) -> None:
        """Wait for user to complete OAuth/Google login manually."""
        log.warning(
            f"{platform}_manual_oauth",
            url=page.url,
            message="Waiting up to 120s for manual Google login...",
        )
        for _ in range(60):
            human_delay(2000, 2500)
            if success_url_part in page.url:
                break
        human_delay(3000, 5000)

    def _login_indeed(self, username: str, password: str) -> Page:
        page = self.context.new_page()

        # Visit homepage first to check session — avoids Cloudflare on /auth
        page.goto("https://www.indeed.com")
        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 3000)

        # Check if already logged in by looking for profile/account indicators
        logged_in = (
            page.locator(
                '[data-gnav-element-name="AccountMenu"], '
                'a[href*="/account"], '
                '[data-testid="gnav-header-account"], '
                "#AccountMenu"
            ).count()
            > 0
        )
        if logged_in:
            log.info("indeed_already_logged_in")
            return page

        # Need to log in — navigate to auth page
        page.goto("https://secure.indeed.com/auth")
        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 3000)

        # Handle Cloudflare / verification challenges
        for _ in range(6):
            title = page.title().lower()
            if "just a moment" in title or "verify" in title:
                log.warning("indeed_challenge_wait")
                human_delay(5000, 8000)
            else:
                break

        # Check if redirected to logged-in state
        if (
            "indeed.com" in page.url
            and "auth" not in page.url
            and "login" not in page.url
        ):
            log.info("indeed_already_logged_in")
            return page

        # Try Google auth button first, fall back to email/password
        google_btn = page.locator(
            'button:has-text("Google"), [data-tn-element="auth-page-google-button"], a[href*="accounts.google.com"]'
        )
        if google_btn.count() > 0:
            human_click(
                page,
                'button:has-text("Google"), [data-tn-element="auth-page-google-button"], a[href*="accounts.google.com"]',
            )
            self._wait_for_oauth_login(page, "indeed", "indeed.com")
        else:
            email_field = page.locator('[name="__email"]')
            if email_field.count() > 0:
                human_type(page, '[name="__email"]', username)
                human_click(page, '[data-tn-element="auth-page-email-submit"]')
                page.wait_for_load_state("domcontentloaded")
                human_delay(1000, 2000)

                human_type(page, '[name="__password"]', password)
                human_click(page, '[data-tn-element="auth-page-sign-in-submit"]')
                page.wait_for_load_state("domcontentloaded")
                human_delay(2000, 4000)
            else:
                log.warning("indeed_login_form_not_found", url=page.url)

        log.info("indeed_login_complete")
        return page

    def _login_glassdoor(self, username: str, password: str) -> Page:
        page = self.context.new_page()

        # Visit homepage first to check session — avoids Cloudflare on login page
        page.goto("https://www.glassdoor.com")
        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 3000)

        # Handle Cloudflare challenge on homepage
        for _ in range(6):
            if "just a moment" in page.title().lower():
                log.warning(
                    "glassdoor_cloudflare_challenge",
                    message="Waiting for Cloudflare...",
                )
                human_delay(5000, 8000)
            else:
                break

        # Check if already logged in
        logged_in = (
            page.locator(
                '[data-test="profile-button"], '
                'a[href*="/member/profile"], '
                "#ProfileButton, "
                '[data-test="header-profile"]'
            ).count()
            > 0
        )
        if logged_in:
            log.info("glassdoor_already_logged_in")
            return page

        # Need to log in — navigate to login page
        page.goto("https://www.glassdoor.com/profile/login_input.htm")
        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 3000)

        # Handle Cloudflare challenge on login page
        for _ in range(6):
            if "just a moment" in page.title().lower():
                log.warning(
                    "glassdoor_cloudflare_challenge",
                    message="Waiting for Cloudflare...",
                )
                human_delay(5000, 8000)
            else:
                break

        # Check if already logged in (redirected away from login)
        if "glassdoor.com" in page.url and "login" not in page.url.lower():
            log.info("glassdoor_already_logged_in")
            return page

        # Try Google auth button first, fall back to email/password
        google_btn = page.locator(
            'button:has-text("Google"), [data-provider="google"], a[href*="accounts.google.com"]'
        )
        if google_btn.count() > 0:
            human_click(
                page,
                'button:has-text("Google"), [data-provider="google"], a[href*="accounts.google.com"]',
            )
            self._wait_for_oauth_login(page, "glassdoor", "glassdoor.com")
        else:
            # Check if login form is actually present
            username_field = page.locator(
                '[name="username"], [name="email"], #userEmail'
            )
            if username_field.count() > 0:
                human_type(
                    page, '[name="username"], [name="email"], #userEmail', username
                )
                human_type(page, '[name="password"]', password)
                human_delay(500, 1000)
                human_click(page, '[type="submit"]')
                page.wait_for_load_state("domcontentloaded")
                human_delay(2000, 4000)
            else:
                log.warning("glassdoor_login_form_not_found", url=page.url)
                # Might already be logged in or Cloudflare blocked us

        log.info("glassdoor_login_complete")
        return page

    def _login_ziprecruiter(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://www.ziprecruiter.com/authn/login")
        page.wait_for_load_state("domcontentloaded")
        human_delay(1000, 2000)

        human_type(page, '[name="email"], #email', username)
        human_type(page, '[name="password"], #password', password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"]')

        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        log.info("ziprecruiter_login_complete")
        return page

    def _login_dice(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://www.dice.com/dashboard/login")
        page.wait_for_load_state("domcontentloaded")
        human_delay(1000, 2000)

        human_type(page, '[name="email"], #email', username)
        human_type(page, '[name="password"], #password', password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"], button:has-text("Sign In")')

        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        log.info("dice_login_complete")
        return page

    def _login_wellfound(self, username: str, password: str) -> Page:
        page = self.context.new_page()
        page.goto("https://wellfound.com/login")
        page.wait_for_load_state("domcontentloaded")
        human_delay(1000, 2000)

        human_type(page, '[name="email"], #user_email', username)
        human_type(page, '[name="password"], #user_password', password)
        human_delay(500, 1000)
        human_click(page, '[type="submit"], button:has-text("Log in")')

        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        log.info("wellfound_login_complete")
        return page
