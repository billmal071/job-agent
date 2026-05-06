"""Platform login flows and session persistence."""

from __future__ import annotations

from playwright.sync_api import BrowserContext, Page

from job_agent.browser.humanizer import human_click, human_delay, human_type
from job_agent.browser.selectors import AUTH_SELECTORS
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
        auth = AUTH_SELECTORS.get(platform.value)
        if not auth:
            return False
        try:
            return page.locator(auth.logged_in_check).count() > 0
        except Exception:
            return False

    def _login_linkedin(self, username: str, password: str) -> Page:
        auth = AUTH_SELECTORS["linkedin"]
        page = self.context.new_page()
        page.goto(auth.homepage_url, wait_until="domcontentloaded")
        human_delay(2000, 3000)

        # Already logged in from saved session
        if self.is_logged_in(Platform.LINKEDIN, page) or (
            "login" not in page.url and "checkpoint" not in page.url
        ):
            log.info("linkedin_session_restored")
            return page

        # Not logged in — go to login page
        page.goto(auth.login_url, wait_until="domcontentloaded")
        human_delay(1000, 2000)

        # Check if login form is present (might be blocked by CAPTCHA/challenge)
        username_field = page.locator(auth.username_field)
        if username_field.count() > 0 and username_field.is_visible():
            human_type(page, auth.username_field, username)
            human_type(page, auth.password_field, password)
            human_delay(500, 1000)
            human_click(page, auth.submit_button)
            page.wait_for_load_state("domcontentloaded")
            human_delay(2000, 4000)
        else:
            log.warning(
                "linkedin_login_form_not_found",
                url=page.url,
                message="Login form not visible — CAPTCHA or challenge page. Waiting for manual login...",
            )

        # Wait for manual resolution if needed (checkpoint, challenge, or still on login)
        if (
            "checkpoint" in page.url
            or "login" in page.url
            or "challenge" in page.url
            or not self.is_logged_in(Platform.LINKEDIN, page)
        ):
            log.warning(
                "linkedin_manual_intervention",
                url=page.url,
                message="Waiting up to 120s for manual login/verification...",
            )
            for _ in range(60):
                human_delay(2000, 2500)
                current = page.url
                if (
                    "checkpoint" not in current
                    and "login" not in current
                    and "challenge" not in current
                ):
                    break
            human_delay(3000, 5000)

        if not self.is_logged_in(Platform.LINKEDIN, page):
            # Fallback: if we're past login/checkpoint, trust it
            current = page.url
            if (
                "checkpoint" not in current
                and "login" not in current
                and "challenge" not in current
            ):
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
        auth = AUTH_SELECTORS["indeed"]
        page = self.context.new_page()

        # Visit homepage first to check session — avoids Cloudflare on /auth
        page.goto(auth.homepage_url)
        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 3000)

        # Check if already logged in by looking for profile/account indicators
        if page.locator(auth.homepage_logged_in_check).count() > 0:
            log.info("indeed_already_logged_in")
            return page

        # Need to log in — navigate to auth page
        page.goto(auth.login_url)
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
        google_btn = page.locator(auth.google_auth_button)
        if google_btn.count() > 0:
            human_click(page, auth.google_auth_button)
            self._wait_for_oauth_login(page, "indeed", "indeed.com")
        else:
            email_field = page.locator(auth.username_field)
            if email_field.count() > 0:
                human_type(page, auth.username_field, username)
                human_click(page, '[data-tn-element="auth-page-email-submit"]')
                page.wait_for_load_state("domcontentloaded")
                human_delay(1000, 2000)

                human_type(page, auth.password_field, password)
                human_click(page, auth.submit_button)
                page.wait_for_load_state("domcontentloaded")
                human_delay(2000, 4000)
            else:
                log.warning("indeed_login_form_not_found", url=page.url)

        log.info("indeed_login_complete")
        return page

    def _login_glassdoor(self, username: str, password: str) -> Page:
        auth = AUTH_SELECTORS["glassdoor"]
        page = self.context.new_page()

        # Visit homepage first to check session — avoids Cloudflare on login page
        page.goto(auth.homepage_url)
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
        if page.locator(auth.homepage_logged_in_check).count() > 0:
            log.info("glassdoor_already_logged_in")
            return page

        # Need to log in — navigate to login page
        page.goto(auth.login_url)
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
        google_btn = page.locator(auth.google_auth_button)
        if google_btn.count() > 0:
            human_click(page, auth.google_auth_button)
            self._wait_for_oauth_login(page, "glassdoor", "glassdoor.com")
        else:
            username_field = page.locator(auth.username_field)
            if username_field.count() > 0:
                human_type(page, auth.username_field, username)
                human_type(page, auth.password_field, password)
                human_delay(500, 1000)
                human_click(page, auth.submit_button)
                page.wait_for_load_state("domcontentloaded")
                human_delay(2000, 4000)
            else:
                log.warning("glassdoor_login_form_not_found", url=page.url)

        log.info("glassdoor_login_complete")
        return page

    def _login_ziprecruiter(self, username: str, password: str) -> Page:
        auth = AUTH_SELECTORS["ziprecruiter"]
        page = self.context.new_page()
        page.goto(auth.login_url)
        page.wait_for_load_state("domcontentloaded")
        human_delay(1000, 2000)

        human_type(page, auth.username_field, username)
        human_type(page, auth.password_field, password)
        human_delay(500, 1000)
        human_click(page, auth.submit_button)

        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        log.info("ziprecruiter_login_complete")
        return page

    def _login_dice(self, username: str, password: str) -> Page:
        auth = AUTH_SELECTORS["dice"]
        page = self.context.new_page()
        page.goto(auth.login_url)
        page.wait_for_load_state("domcontentloaded")
        human_delay(1000, 2000)

        human_type(page, auth.username_field, username)
        human_type(page, auth.password_field, password)
        human_delay(500, 1000)
        human_click(page, auth.submit_button)

        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        log.info("dice_login_complete")
        return page

    def _login_wellfound(self, username: str, password: str) -> Page:
        auth = AUTH_SELECTORS["wellfound"]
        page = self.context.new_page()
        page.goto(auth.login_url)
        page.wait_for_load_state("domcontentloaded")
        human_delay(1000, 2000)

        human_type(page, auth.username_field, username)
        human_type(page, auth.password_field, password)
        human_delay(500, 1000)
        human_click(page, auth.submit_button)

        page.wait_for_load_state("domcontentloaded")
        human_delay(2000, 4000)

        log.info("wellfound_login_complete")
        return page
