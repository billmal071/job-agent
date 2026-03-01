"""Tests for platform drivers (shared patterns across all 6)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting


def _make_job(platform=Platform.LINKEDIN) -> JobPosting:
    return JobPosting(
        external_id="j1",
        platform=platform,
        title="Engineer",
        company="Acme",
        url="https://example.com/job/1",
    )


# --------------- LinkedIn ---------------

class TestLinkedInDriver:
    @pytest.fixture
    def driver(self, settings):
        bm = MagicMock()
        from job_agent.platforms.linkedin.driver import LinkedInDriver
        return LinkedInDriver(settings, bm)

    def test_ensure_page_raises_when_not_logged_in(self, driver):
        with pytest.raises(RuntimeError, match="Not logged in"):
            driver._ensure_page()

    def test_apply_delegates_to_applicator(self, driver):
        driver._applicator = MagicMock()
        driver._applicator.apply.return_value = True
        job = _make_job()
        assert driver.apply(job, "/r.pdf") is True
        driver._applicator.apply.assert_called_once()

    def test_close_saves_state(self, driver):
        driver._page = MagicMock()
        driver.close()
        driver.browser.save_state.assert_called_with("linkedin")


# --------------- Indeed ---------------

class TestIndeedDriver:
    @pytest.fixture
    def driver(self, settings):
        bm = MagicMock()
        from job_agent.platforms.indeed.driver import IndeedDriver
        return IndeedDriver(settings, bm)

    def test_ensure_page_raises_when_not_logged_in(self, driver):
        with pytest.raises(RuntimeError, match="Not logged in"):
            driver._ensure_page()


# --------------- Glassdoor ---------------

class TestGlassdoorDriver:
    @pytest.fixture
    def driver(self, settings):
        bm = MagicMock()
        from job_agent.platforms.glassdoor.driver import GlassdoorDriver
        return GlassdoorDriver(settings, bm)

    def test_ensure_page_raises_when_not_logged_in(self, driver):
        with pytest.raises(RuntimeError, match="Not logged in"):
            driver._ensure_page()


# --------------- Dice ---------------

class TestDiceDriver:
    @pytest.fixture
    def driver(self, settings):
        bm = MagicMock()
        from job_agent.platforms.dice.driver import DiceDriver
        return DiceDriver(settings, bm)

    def test_ensure_page_raises_when_not_logged_in(self, driver):
        with pytest.raises(RuntimeError, match="Not logged in"):
            driver._ensure_page()


# --------------- Wellfound ---------------

class TestWellfoundDriver:
    @pytest.fixture
    def driver(self, settings):
        bm = MagicMock()
        from job_agent.platforms.wellfound.driver import WellfoundDriver
        return WellfoundDriver(settings, bm)

    def test_ensure_page_raises_when_not_logged_in(self, driver):
        with pytest.raises(RuntimeError, match="Not logged in"):
            driver._ensure_page()


# --------------- ZipRecruiter ---------------

class TestZipRecruiterDriver:
    @pytest.fixture
    def driver(self, settings):
        bm = MagicMock()
        from job_agent.platforms.ziprecruiter.driver import ZipRecruiterDriver
        return ZipRecruiterDriver(settings, bm)

    def test_ensure_page_raises_when_not_logged_in(self, driver):
        with pytest.raises(RuntimeError, match="Not logged in"):
            driver._ensure_page()
