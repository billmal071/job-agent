"""Tests for external-ATS delegation in the thin platform applicators.

When ZipRecruiter/Wellfound/Glassdoor/Dice redirect to an external ATS
(Greenhouse, Lever, etc.), the applicator must hand off to
ExternalATSApplicator instead of failing the application.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting
from job_agent.platforms.dice.applicator import DiceApplicator
from job_agent.platforms.glassdoor.applicator import GlassdoorApplicator
from job_agent.platforms.wellfound.applicator import WellfoundApplicator
from job_agent.platforms.ziprecruiter.applicator import ZipRecruiterApplicator

EXTERNAL_URL = "https://boards.greenhouse.io/acme/jobs/123"

# (applicator class, platform, module path for human_delay patching)
_CASES = [
    (
        ZipRecruiterApplicator,
        Platform.ZIPRECRUITER,
        "job_agent.platforms.ziprecruiter.applicator",
    ),
    (
        WellfoundApplicator,
        Platform.WELLFOUND,
        "job_agent.platforms.wellfound.applicator",
    ),
    (
        GlassdoorApplicator,
        Platform.GLASSDOOR,
        "job_agent.platforms.glassdoor.applicator",
    ),
    (DiceApplicator, Platform.DICE, "job_agent.platforms.dice.applicator"),
]


def _make_job(platform: Platform) -> JobPosting:
    return JobPosting(
        external_id="j1",
        platform=platform,
        title="Engineer",
        company="Acme",
        url="https://example.com/job/1",
    )


def _page_redirected_to(url: str) -> MagicMock:
    """Mock page with a visible apply button whose URL is *url* after the click."""
    page = MagicMock()
    page.url = url
    page.context.pages = [page]
    button = MagicMock()
    button.count.return_value = 1
    locator = MagicMock()
    locator.first = button
    locator.count.return_value = 1
    page.locator.return_value = locator
    return page


def _external_tab(url: str = EXTERNAL_URL) -> MagicMock:
    tab = MagicMock()
    tab.url = url
    return tab


def _click_opens(page: MagicMock, *tabs: MagicMock) -> None:
    """Make clicking the apply button add *tabs* to the context, like a popup."""
    page.locator.return_value.first.click.side_effect = lambda *a, **kw: (
        page.context.pages.extend(tabs)
    )


def _popup_arrives_during_wait(page: MagicMock, *tabs: MagicMock) -> None:
    """Deliver *tabs* only when the pre-click page waiter completes.

    Simulates a popup that opens after ``click()`` returns: the click itself
    adds nothing; the ``context.expect_page`` waiter picks it up.
    """
    waiter = MagicMock()

    def _exit(*args, **kwargs):
        page.context.pages.extend(tabs)
        return False

    waiter.__enter__ = MagicMock(return_value=waiter)
    waiter.__exit__ = MagicMock(side_effect=_exit)
    page.context.expect_page.return_value = waiter


@pytest.mark.parametrize("cls,platform,module", _CASES)
class TestExternalATSDelegation:
    def _run_do_apply(self, cls, platform, module, settings, mock_rate_limiter):
        # Tracking params naming the job board must not defeat redirect detection
        page = _page_redirected_to(f"{EXTERNAL_URL}?source={platform.value}.com")
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats = mock_ats_cls.return_value
            mock_ats.apply.return_value = True
            result = applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        return result, mock_ats_cls, mock_ats, job, page

    def test_delegates_on_external_redirect(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        result, mock_ats_cls, mock_ats, job, page = self._run_do_apply(
            cls, platform, module, settings, mock_rate_limiter
        )
        mock_ats_cls.assert_called_once()
        assert mock_ats_cls.call_args.args[0] is page
        mock_ats.apply.assert_called_once_with(job, "/r.pdf", "/cl.pdf")
        assert result is True

    def test_external_ats_failure_propagates_as_false(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        page = _page_redirected_to(EXTERNAL_URL)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats_cls.return_value.apply.return_value = False
            result = applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        assert result is False

    def test_delegates_when_redirect_opens_popup(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """A new tab showing the external ATS is used for delegation, then closed."""
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        popup = _external_tab()
        _click_opens(page, popup)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats_cls.return_value.apply.return_value = True
            result = applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        assert result is True
        assert mock_ats_cls.call_args.args[0] is popup
        popup.close.assert_called_once()

    def test_delegates_when_external_popup_is_not_newest_tab(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """The external tab is found even when an on-platform tab is newer."""
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        popup = _external_tab()
        newer_platform_tab = _external_tab(f"https://www.{platform.value}.com/other")
        _click_opens(page, popup, newer_platform_tab)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats_cls.return_value.apply.return_value = True
            result = applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        assert result is True
        assert mock_ats_cls.call_args.args[0] is popup
        popup.close.assert_called_once()

    def test_popup_closed_when_delegation_raises(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        popup = _external_tab()
        _click_opens(page, popup)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats_cls.return_value.apply.side_effect = RuntimeError("ats blew up")
            with pytest.raises(RuntimeError):
                applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        popup.close.assert_called_once()

    def test_click_timeout_propagates_and_is_retryable(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """A timeout from the click itself must surface for retry handling."""
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        err = PlaywrightTimeoutError("Timeout 30000ms exceeded")
        page.locator.return_value.first.click.side_effect = err
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with patch(f"{module}.human_delay"):
            with pytest.raises(PlaywrightTimeoutError):
                applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        assert applicator._is_retryable_error(err) is True

    def test_popup_wait_timeout_alone_continues_native_flow(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """expect_page timing out (no popup) is not an error — native flow runs."""
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        waiter = MagicMock()
        waiter.__enter__ = MagicMock(return_value=waiter)
        waiter.__exit__ = MagicMock(
            side_effect=PlaywrightTimeoutError("Timeout 5000ms exceeded")
        )
        page.context.expect_page.return_value = waiter
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        mock_ats_cls.assert_not_called()

    def test_delegates_when_popup_opens_after_click_returns(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """The pre-click waiter catches a popup created after click() returns."""
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        popup = _external_tab()
        _popup_arrives_during_wait(page, popup)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats_cls.return_value.apply.return_value = True
            result = applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        assert result is True
        assert mock_ats_cls.call_args.args[0] is popup
        popup.close.assert_called_once()

    def test_waits_for_blank_popup_to_navigate(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """A popup still at about:blank is given time to reach its real URL."""
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        popup = _external_tab()
        urls = iter(["about:blank", "about:blank", EXTERNAL_URL])
        type(popup).url = PropertyMock(side_effect=lambda: next(urls, EXTERNAL_URL))
        _click_opens(page, popup)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats_cls.return_value.apply.return_value = True
            result = applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        assert result is True
        assert mock_ats_cls.call_args.args[0] is popup
        popup.close.assert_called_once()

    def test_blank_popup_that_never_navigates_falls_back_to_native_flow(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        popup = _external_tab("about:blank")
        _click_opens(page, popup)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch.object(cls, "_wait_for_page_url", return_value="about:blank"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        mock_ats_cls.assert_not_called()

    def test_ignores_stale_external_tab_when_no_redirect(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """A pre-existing external tab from an earlier apply is never picked up."""
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        stale = _external_tab("https://jobs.lever.co/other-co/999")
        page.context.pages = [page, stale]
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        mock_ats_cls.assert_not_called()
        stale.close.assert_not_called()

    def test_new_popup_chosen_over_stale_external_tab(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """With a stale external tab open, delegation targets only the new popup."""
        page = _page_redirected_to(f"https://www.{platform.value}.com/job/1")
        stale = _external_tab("https://jobs.lever.co/other-co/999")
        page.context.pages = [page, stale]
        popup = _external_tab()
        _click_opens(page, popup)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats_cls.return_value.apply.return_value = True
            result = applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        assert result is True
        assert mock_ats_cls.call_args.args[0] is popup
        popup.close.assert_called_once()
        stale.close.assert_not_called()

    def test_no_delegation_when_still_on_platform(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        # Tracking params naming another domain must not trigger delegation
        page = _page_redirected_to(
            f"https://www.{platform.value}.com/job/1?ref=greenhouse.io"
        )
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            applicator._do_apply(job, "/r.pdf", "/cl.pdf", None)
        mock_ats_cls.assert_not_called()

    def test_external_ats_crash_recorded_as_failure(
        self, cls, platform, module, settings, mock_rate_limiter
    ):
        """An exception inside the external ATS handler must not escape apply()."""
        page = _page_redirected_to(EXTERNAL_URL)
        applicator = cls(page, mock_rate_limiter, settings)
        job = _make_job(platform)
        with (
            patch(f"{module}.human_delay"),
            patch("job_agent.platforms.base_applicator.human_delay"),
            patch.object(applicator, "_navigate_to_job"),
            patch.object(applicator, "_take_screenshot"),
            patch(
                "job_agent.platforms.external_ats.ExternalATSApplicator"
            ) as mock_ats_cls,
        ):
            mock_ats_cls.return_value.apply.side_effect = RuntimeError("ats blew up")
            result = applicator.apply(job, "/r.pdf")
        assert result is False
        mock_rate_limiter.failure.assert_called_once()
