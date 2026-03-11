"""Unit tests for job_agent.platforms.external_ats."""

from __future__ import annotations

from unittest.mock import MagicMock

from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting
from job_agent.platforms.external_ats import ATSInfo, ExternalATSApplicator, detect_ats


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(**overrides) -> JobPosting:
    defaults = dict(
        external_id="j1",
        platform=Platform.LINKEDIN,
        title="Software Engineer",
        company="Acme Corp",
    )
    defaults.update(overrides)
    return JobPosting(**defaults)


def _make_page(url: str = "https://example.com", body_text: str = "") -> MagicMock:
    """Return a minimal mock Playwright Page."""
    page = MagicMock()
    page.url = url

    # page.locator("body").inner_text() -> body_text
    body_locator = MagicMock()
    body_locator.inner_text.return_value = body_text

    # page.locator('a[href^="mailto:"]').all() -> [] (no mailto links by default)
    mailto_locator = MagicMock()
    mailto_locator.all.return_value = []

    # page.locator("form, input[type='file'], input[type='text']").count() -> 1
    form_locator = MagicMock()
    form_locator.count.return_value = 1

    def locator_side_effect(selector):
        if selector == "body":
            return body_locator
        if selector.startswith('a[href^="mailto:"]'):
            return mailto_locator
        if "form" in selector and "input[type='file']" in selector:
            return form_locator
        return MagicMock()

    page.locator.side_effect = locator_side_effect
    return page


# ---------------------------------------------------------------------------
# detect_ats() — pure function tests
# ---------------------------------------------------------------------------


def test_detect_ats_greenhouse():
    result = detect_ats("https://boards.greenhouse.io/acme/jobs/123")
    assert isinstance(result, ATSInfo)
    assert result.name == "greenhouse"


def test_detect_ats_lever():
    result = detect_ats("https://jobs.lever.co/acme/abc-def-123")
    assert isinstance(result, ATSInfo)
    assert result.name == "lever"


def test_detect_ats_ashby():
    result = detect_ats("https://jobs.ashbyhq.com/acme/senior-engineer")
    assert isinstance(result, ATSInfo)
    assert result.name == "ashby"


def test_detect_ats_workday():
    result = detect_ats("https://acme.myworkdayjobs.com/en-US/careers/job/123")
    assert isinstance(result, ATSInfo)
    assert result.name == "workday"


def test_detect_ats_unknown():
    result = detect_ats("https://www.randomjobsite.example.com/jobs/456")
    assert result is None


# ---------------------------------------------------------------------------
# ExternalATSApplicator.apply() — still on job board
# ---------------------------------------------------------------------------


def test_apply_still_on_job_board():
    page = _make_page(url="https://www.indeed.com/viewjob?jk=abc123")
    applicator = ExternalATSApplicator(page=page, answerer=None)
    job = _make_job()
    result = applicator.apply(job, resume_path="/tmp/resume.pdf")
    assert result is False


# ---------------------------------------------------------------------------
# ExternalATSApplicator._check_success()
# ---------------------------------------------------------------------------


def test_check_success_finds_phrase():
    page = _make_page(
        url="https://boards.greenhouse.io/acme/applications/12345",
        body_text="Application Submitted! We will be in touch soon.",
    )
    applicator = ExternalATSApplicator(page=page, answerer=None)
    assert applicator._check_success() is True


def test_check_success_url_pattern():
    page = _make_page(
        url="https://jobs.lever.co/acme/abc/thank-you",
        body_text="Some generic page content with no success keywords.",
    )
    applicator = ExternalATSApplicator(page=page, answerer=None)
    assert applicator._check_success() is True


def test_check_success_no_match():
    page = _make_page(
        url="https://jobs.ashbyhq.com/acme/apply",
        body_text="Please fill out the form below to apply for this position.",
    )
    applicator = ExternalATSApplicator(page=page, answerer=None)
    assert applicator._check_success() is False
