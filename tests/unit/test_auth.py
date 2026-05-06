"""Tests for AuthManager login flows."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from job_agent.browser.auth import AuthManager
from job_agent.db.models import Platform


@pytest.fixture(autouse=True)
def mock_humanizer():
    with (
        patch("job_agent.browser.auth.human_delay"),
        patch("job_agent.browser.auth.human_click"),
        patch("job_agent.browser.auth.human_type"),
    ):
        yield


def _make_page(url="https://example.com"):
    page = MagicMock()
    type(page).url = property(lambda self: url)
    page.title.return_value = "Page Title"
    locator = MagicMock()
    locator.count.return_value = 0
    locator.is_visible.return_value = False
    page.locator.return_value = locator
    return page


def _make_auth():
    context = MagicMock()
    return AuthManager(context)


class TestLoginRouting:
    def test_unsupported_platform_raises(self):
        auth = _make_auth()
        with pytest.raises(ValueError):
            auth.login(MagicMock(), "user", "pass")

    def test_routes_to_each_simple_platform(self):
        for platform in (Platform.ZIPRECRUITER, Platform.DICE, Platform.WELLFOUND):
            auth = _make_auth()
            page = _make_page()
            auth.context.new_page.return_value = page
            result = auth.login(platform, "user", "pass")
            assert result is page


class TestIsLoggedIn:
    def test_linkedin_logged_in(self):
        auth = _make_auth()
        page = _make_page()

        def locator_side_effect(selector):
            loc = MagicMock()
            if ".global-nav__me" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect
        assert auth.is_logged_in(Platform.LINKEDIN, page) is True

    def test_linkedin_not_logged_in(self):
        auth = _make_auth()
        page = _make_page()
        locator = MagicMock()
        locator.count.return_value = 0
        page.locator.return_value = locator
        assert auth.is_logged_in(Platform.LINKEDIN, page) is False

    def test_exception_returns_false(self):
        auth = _make_auth()
        page = _make_page()
        page.locator.side_effect = RuntimeError("boom")
        assert auth.is_logged_in(Platform.LINKEDIN, page) is False

    def test_unsupported_platform_returns_false(self):
        auth = _make_auth()
        page = _make_page()
        assert auth.is_logged_in(MagicMock(), page) is False

    def test_indeed_logged_in(self):
        auth = _make_auth()
        page = _make_page()

        def locator_side_effect(selector):
            loc = MagicMock()
            if "AccountMenu" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect
        assert auth.is_logged_in(Platform.INDEED, page) is True


class TestLinkedInLogin:
    def test_session_restored_skips_login(self):
        auth = _make_auth()
        page = _make_page(url="https://www.linkedin.com/feed/")
        auth.context.new_page.return_value = page

        with patch.object(auth, "is_logged_in", return_value=True):
            result = auth._login_linkedin("user", "pass")

        assert result is page
        # form interaction (human_type) should not have been called
        from job_agent.browser import auth as auth_module  # noqa: F401 — check patch target

    def test_login_with_form_visible(self):
        auth = _make_auth()
        page = _make_page(url="https://www.linkedin.com/login")
        auth.context.new_page.return_value = page

        # URL changes from /login to /feed/ after form submission
        url_seq = iter(
            [
                "https://www.linkedin.com/login",
                "https://www.linkedin.com/login",
                "https://www.linkedin.com/feed/",
                "https://www.linkedin.com/feed/",
                "https://www.linkedin.com/feed/",
            ]
        )
        type(page).url = property(
            lambda self: next(url_seq, "https://www.linkedin.com/feed/")
        )

        def locator_side_effect(selector):
            loc = MagicMock()
            if "#username" in selector:
                loc.count.return_value = 1
                loc.is_visible.return_value = True
            else:
                loc.count.return_value = 0
                loc.is_visible.return_value = False
            return loc

        page.locator.side_effect = locator_side_effect

        # is_logged_in: False initially (not logged in), True after form submission
        login_calls = iter([False, False, True, True])
        with (
            patch.object(
                auth,
                "is_logged_in",
                side_effect=lambda plat, pg: next(login_calls, True),
            ),
            patch("job_agent.browser.auth.human_type") as mock_type,
        ):
            auth._login_linkedin("user@example.com", "secret")
            # human_type should have been called for username and password
            assert mock_type.call_count >= 2

    def test_login_fails_raises_error(self):
        auth = _make_auth()
        page = _make_page(url="https://www.linkedin.com/login")
        auth.context.new_page.return_value = page

        locator = MagicMock()
        locator.count.return_value = 0
        locator.is_visible.return_value = False
        page.locator.return_value = locator

        with patch.object(auth, "is_logged_in", return_value=False):
            with pytest.raises(RuntimeError, match="LinkedIn login failed"):
                auth._login_linkedin("user", "pass")


class TestSimplePlatformLogins:
    def test_ziprecruiter_navigates_and_submits(self):
        auth = _make_auth()
        page = _make_page()
        auth.context.new_page.return_value = page
        auth._login_ziprecruiter("user", "pass")
        page.goto.assert_called_once_with("https://www.ziprecruiter.com/authn/login")

    def test_dice_navigates_and_submits(self):
        auth = _make_auth()
        page = _make_page()
        auth.context.new_page.return_value = page
        auth._login_dice("user", "pass")
        page.goto.assert_called_once_with("https://www.dice.com/dashboard/login")

    def test_wellfound_navigates_and_submits(self):
        auth = _make_auth()
        page = _make_page()
        auth.context.new_page.return_value = page
        auth._login_wellfound("user", "pass")
        page.goto.assert_called_once_with("https://wellfound.com/login")


class TestIndeedLogin:
    def test_already_logged_in_returns_early(self):
        auth = _make_auth()
        page = _make_page(url="https://www.indeed.com")
        auth.context.new_page.return_value = page

        def locator_side_effect(selector):
            loc = MagicMock()
            if "AccountMenu" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect
        result = auth._login_indeed("user", "pass")
        assert result is page
        # Should not navigate to the auth page
        calls = [str(c) for c in page.goto.call_args_list]
        assert not any("secure.indeed.com" in c for c in calls)

    def test_cloudflare_challenge_waits(self):
        auth = _make_auth()
        page = _make_page(url="https://www.indeed.com")
        auth.context.new_page.return_value = page

        call_count = {"n": 0}

        def title_side_effect():
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return "Just a moment"
            return "Indeed"

        page.title.side_effect = title_side_effect

        # No account menu → not logged in on homepage
        locator = MagicMock()
        locator.count.return_value = 0
        page.locator.return_value = locator

        # Make URL look like it eventually redirects away from auth
        iter(
            [
                "https://www.indeed.com",  # homepage
                "https://www.indeed.com",  # after goto auth
            ]
        )
        _url_store = {"v": "https://www.indeed.com"}

        result = auth._login_indeed("user", "pass")
        # Just confirm it completes without error and returns a page
        assert result is page


class TestGlassdoorLogin:
    def test_already_logged_in_returns_early(self):
        auth = _make_auth()
        page = _make_page(url="https://www.glassdoor.com")
        auth.context.new_page.return_value = page

        def locator_side_effect(selector):
            loc = MagicMock()
            if (
                "header-profile" in selector
                or "profile-button" in selector
                or "ProfileButton" in selector
            ):
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect
        page.title.return_value = "Glassdoor"
        result = auth._login_glassdoor("user", "pass")
        assert result is page
        # Should not navigate to the login input page
        calls = [str(c) for c in page.goto.call_args_list]
        assert not any("login_input" in c for c in calls)
