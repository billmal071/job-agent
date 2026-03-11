"""Unit tests for OrchestratorEngine.run_once."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.config import Settings
from job_agent.db.models import AgentRun, Base, RunStatus
from job_agent.orchestrator.engine import OrchestratorEngine


@pytest.fixture()
def settings():
    """Settings with a narrow activity window for easy override in tests."""
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
    )


@pytest.fixture()
def in_memory_session():
    """Return a factory that builds sessions against a shared in-memory engine."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    sessions: list = []

    def _factory(*args, **kwargs):
        s = Session()
        sessions.append(s)
        return s

    yield _factory

    for s in sessions:
        s.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_now(hour: int):
    """Return a datetime whose .hour == ``hour``."""
    return datetime(2026, 3, 11, hour, 0, 0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunOnceOutsideActivityWindow:
    """Engine returns zeros and CANCELS the run when outside the window."""

    def test_returns_all_zeros(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 8
        settings.agent.activity_end_hour = 10

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=in_memory_session,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _make_fake_now(hour=23)

            result = engine.run_once("profile.yaml", "linkedin")

        assert result == {
            "discovered": 0,
            "matched": 0,
            "applied": 0,
            "queued": 0,
            "skipped": 0,
        }

    def test_agent_run_status_is_cancelled(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 8
        settings.agent.activity_end_hour = 10

        captured_sessions: list = []

        def capturing_factory(*args, **kwargs):
            s = in_memory_session()
            captured_sessions.append(s)
            return s

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=capturing_factory,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
        ):
            mock_dt.now.return_value = _make_fake_now(hour=23)
            engine.run_once("profile.yaml", "linkedin")

        # The session was closed by run_once, but we can still query via a new
        # session on the same in-memory engine — use the captured session object
        # before close was final (expire_on_commit=False keeps data accessible).
        session = captured_sessions[0]
        run = session.query(AgentRun).first()
        assert run is not None
        assert run.status == RunStatus.CANCELLED
        assert "activity" in (run.error_message or "").lower()

    def test_run_pipeline_not_called(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 8
        settings.agent.activity_end_hour = 10

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=in_memory_session,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
            patch("job_agent.orchestrator.engine.run_pipeline") as mock_pipeline,
        ):
            mock_dt.now.return_value = _make_fake_now(hour=23)
            engine.run_once("profile.yaml", "linkedin")

        mock_pipeline.assert_not_called()


class TestRunOnceInsideActivityWindow:
    """Engine calls run_pipeline and records the stats when inside the window."""

    FAKE_STATS = {
        "discovered": 10,
        "matched": 5,
        "applied": 3,
        "queued": 2,
        "skipped": 0,
    }

    def test_returns_pipeline_stats(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 8
        settings.agent.activity_end_hour = 23

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=in_memory_session,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
            patch(
                "job_agent.orchestrator.engine.run_pipeline",
                return_value=self.FAKE_STATS,
            ),
        ):
            mock_dt.now.return_value = _make_fake_now(hour=12)
            result = engine.run_once("profile.yaml", "linkedin")

        assert result == self.FAKE_STATS

    def test_agent_run_status_is_completed(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 8
        settings.agent.activity_end_hour = 23

        captured_sessions: list = []

        def capturing_factory(*args, **kwargs):
            s = in_memory_session()
            captured_sessions.append(s)
            return s

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=capturing_factory,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
            patch(
                "job_agent.orchestrator.engine.run_pipeline",
                return_value=self.FAKE_STATS,
            ),
        ):
            mock_dt.now.return_value = _make_fake_now(hour=12)
            engine.run_once("profile.yaml", "linkedin")

        session = captured_sessions[0]
        run = session.query(AgentRun).first()
        assert run is not None
        assert run.status == RunStatus.COMPLETED
        assert run.jobs_discovered == 10
        assert run.jobs_matched == 5
        assert run.jobs_applied == 3
        assert run.jobs_queued == 2
        assert run.jobs_skipped == 0

    def test_platform_recorded_on_agent_run(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 8
        settings.agent.activity_end_hour = 23

        captured_sessions: list = []

        def capturing_factory(*args, **kwargs):
            s = in_memory_session()
            captured_sessions.append(s)
            return s

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=capturing_factory,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
            patch(
                "job_agent.orchestrator.engine.run_pipeline",
                return_value=self.FAKE_STATS,
            ),
        ):
            mock_dt.now.return_value = _make_fake_now(hour=12)
            engine.run_once("profile.yaml", "indeed")

        session = captured_sessions[0]
        run = session.query(AgentRun).first()
        assert run.platform == "indeed"
        assert run.profile_name == "profile.yaml"

    def test_platform_defaults_to_all(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 8
        settings.agent.activity_end_hour = 23

        captured_sessions: list = []

        def capturing_factory(*args, **kwargs):
            s = in_memory_session()
            captured_sessions.append(s)
            return s

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=capturing_factory,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
            patch(
                "job_agent.orchestrator.engine.run_pipeline",
                return_value=self.FAKE_STATS,
            ),
        ):
            mock_dt.now.return_value = _make_fake_now(hour=12)
            engine.run_once("profile.yaml")  # no platform arg

        session = captured_sessions[0]
        run = session.query(AgentRun).first()
        assert run.platform == "all"


class TestRunOncePipelineError:
    """Engine sets FAILED status and re-raises when run_pipeline raises."""

    def test_reraises_exception(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 0
        settings.agent.activity_end_hour = 24

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=in_memory_session,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
            patch(
                "job_agent.orchestrator.engine.run_pipeline",
                side_effect=RuntimeError("boom"),
            ),
        ):
            mock_dt.now.return_value = _make_fake_now(hour=12)
            with pytest.raises(RuntimeError, match="boom"):
                engine.run_once("profile.yaml", "linkedin")

    def test_agent_run_status_is_failed(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 0
        settings.agent.activity_end_hour = 24

        captured_sessions: list = []

        def capturing_factory(*args, **kwargs):
            s = in_memory_session()
            captured_sessions.append(s)
            return s

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=capturing_factory,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
            patch(
                "job_agent.orchestrator.engine.run_pipeline",
                side_effect=RuntimeError("pipeline exploded"),
            ),
        ):
            mock_dt.now.return_value = _make_fake_now(hour=12)
            with pytest.raises(RuntimeError):
                engine.run_once("profile.yaml", "linkedin")

        session = captured_sessions[0]
        run = session.query(AgentRun).first()
        assert run is not None
        assert run.status == RunStatus.FAILED

    def test_error_message_recorded(self, settings, in_memory_session):
        settings.agent.activity_start_hour = 0
        settings.agent.activity_end_hour = 24

        captured_sessions: list = []

        def capturing_factory(*args, **kwargs):
            s = in_memory_session()
            captured_sessions.append(s)
            return s

        engine = OrchestratorEngine(settings)

        with (
            patch(
                "job_agent.orchestrator.engine.get_session",
                side_effect=capturing_factory,
            ),
            patch("job_agent.orchestrator.engine.datetime") as mock_dt,
            patch(
                "job_agent.orchestrator.engine.run_pipeline",
                side_effect=RuntimeError("pipeline exploded"),
            ),
        ):
            mock_dt.now.return_value = _make_fake_now(hour=12)
            with pytest.raises(RuntimeError):
                engine.run_once("profile.yaml", "linkedin")

        session = captured_sessions[0]
        run = session.query(AgentRun).first()
        assert "pipeline exploded" in run.error_message
