"""Tests for external-ATS delegation in the thin platform applicators.

When ZipRecruiter/Wellfound/Glassdoor/Dice redirect to an external ATS
(Greenhouse, Lever, etc.), the applicator must hand off to
ExternalATSApplicator instead of failing the application.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
        popup = MagicMock()
        popup.url = EXTERNAL_URL
        page.context.pages = [page, popup]
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
