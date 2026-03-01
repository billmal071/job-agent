"""Tests for BaseApplicator template method pattern."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting
from job_agent.platforms.base_applicator import BaseApplicator


# Concrete subclass for testing
class _StubApplicator(BaseApplicator):
    """Minimal concrete applicator for tests."""

    do_apply_return: bool = True
    do_apply_called: bool = False

    def _do_apply(self, job, resume_path, cover_letter_path, answers):
        self.do_apply_called = True
        return self.do_apply_return


def _make_job(**overrides) -> JobPosting:
    defaults = dict(
        external_id="j1",
        platform=Platform.LINKEDIN,
        title="Engineer",
        company="Acme",
        url="https://example.com/job/1",
    )
    defaults.update(overrides)
    return JobPosting(**defaults)


@pytest.fixture
def applicator(mock_page, mock_rate_limiter, settings):
    return _StubApplicator(mock_page, mock_rate_limiter, settings)


# ------------------------------------------------------------------


class TestDryRun:
    def test_returns_true_without_navigating(self, applicator, mock_page):
        applicator.settings.agent.dry_run = True
        result = applicator.apply(_make_job(), "/resume.pdf")
        assert result is True
        mock_page.goto.assert_not_called()


class TestCircuitBreaker:
    def test_open_returns_false(self, applicator, mock_rate_limiter):
        mock_rate_limiter.wait.return_value = False
        result = applicator.apply(_make_job(), "/resume.pdf")
        assert result is False


class TestScreenshotOnError:
    def test_screenshot_taken_on_error(self, applicator, mock_page):
        applicator.do_apply_return = False

        # Make _do_apply raise
        def _raise(*a, **kw):
            raise RuntimeError("test error")

        applicator._do_apply = _raise

        with patch.object(applicator, "_take_screenshot") as mock_ss:
            applicator.apply(_make_job(), "/resume.pdf")
            mock_ss.assert_called_once()


class TestRetry:
    def test_retry_on_timeout(self, applicator, mock_page):
        calls = []

        def _do(job, rp, cl, ans):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("Timeout 30000ms exceeded")
            return True

        applicator._do_apply = _do

        with patch("job_agent.platforms.base_applicator.human_delay"):
            result = applicator.apply(_make_job(), "/r.pdf")

        assert result is True
        assert len(calls) == 2

    def test_no_retry_on_non_retryable(self, applicator):
        calls = []

        def _do(job, rp, cl, ans):
            calls.append(1)
            raise RuntimeError("No apply button found")

        applicator._do_apply = _do

        with patch.object(applicator, "_take_screenshot"):
            applicator.apply(_make_job(), "/r.pdf")

        assert len(calls) == 1


class TestSuccessCallback:
    def test_rate_limiter_success_on_apply(self, applicator, mock_rate_limiter):
        applicator.do_apply_return = True
        applicator.apply(_make_job(), "/r.pdf")
        mock_rate_limiter.success.assert_called_once()

    def test_rate_limiter_failure_on_error(self, applicator, mock_rate_limiter):
        def _raise(*a, **kw):
            raise RuntimeError("kaboom")

        applicator._do_apply = _raise

        with patch.object(applicator, "_take_screenshot"):
            applicator.apply(_make_job(), "/r.pdf")

        mock_rate_limiter.failure.assert_called_once()
