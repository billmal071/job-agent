"""Tests for shared bot command handler."""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.bots.commands import BotCommandHandler
from job_agent.config import Settings
from job_agent.db.models import Base, Job, JobStatus, Platform
from job_agent.db.session import reset_engine


def _setup():
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )

    return engine, session, settings


def test_handle_queue_empty():
    engine, session, settings = _setup()
    try:
        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            result = handler.handle_queue()
            assert "No jobs" in result
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_handle_queue_with_jobs():
    engine, session, settings = _setup()
    try:
        job = Job(
            external_id="q-1",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="TestCo",
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()

        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            result = handler.handle_queue()
            assert "Dev" in result
            assert "TestCo" in result
            assert f"#{job.id}" in result
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_handle_approve():
    engine, session, settings = _setup()
    try:
        job = Job(
            external_id="a-1",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="ApproveCo",
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()

        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            result = handler.handle_approve(job.id)
            assert "Approved" in result
            assert "ApproveCo" in result

            refreshed = session.get(Job, job.id)
            assert refreshed.status == JobStatus.APPROVED
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_handle_reject():
    engine, session, settings = _setup()
    try:
        job = Job(
            external_id="r-1",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="RejectCo",
            status=JobStatus.QUEUED,
        )
        session.add(job)
        session.commit()

        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            result = handler.handle_reject(job.id)
            assert "Rejected" in result

            refreshed = session.get(Job, job.id)
            assert refreshed.status == JobStatus.REJECTED
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_handle_approve_not_found():
    engine, session, settings = _setup()
    try:
        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            result = handler.handle_approve(999)
            assert "not found" in result
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_handle_approve_not_queued():
    engine, session, settings = _setup()
    try:
        job = Job(
            external_id="nq-1",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="Co",
            status=JobStatus.APPROVED,
        )
        session.add(job)
        session.commit()

        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            result = handler.handle_approve(job.id)
            assert "not queued" in result
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_handle_stats():
    engine, session, settings = _setup()
    try:
        session.add(
            Job(
                external_id="s-1",
                platform=Platform.LINKEDIN,
                title="Dev",
                company="Co",
                status=JobStatus.QUEUED,
            )
        )
        session.commit()

        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            result = handler.handle_stats()
            assert "Stats Summary" in result
            assert "Total jobs: 1" in result
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_handle_bookmarks():
    engine, session, settings = _setup()
    try:
        job = Job(
            external_id="b-1",
            platform=Platform.LINKEDIN,
            title="BookmarkedDev",
            company="BkCo",
            bookmarked=True,
        )
        session.add(job)
        session.commit()

        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            result = handler.handle_bookmarks()
            assert "BookmarkedDev" in result
            assert "BkCo" in result
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_route_command():
    engine, session, settings = _setup()
    try:
        with patch("job_agent.bots.commands.get_session", return_value=session):
            handler = BotCommandHandler(settings)
            assert "Available commands" in handler.route_command("/help")
            assert "Available commands" in handler.route_command("/start")
            assert "No jobs" in handler.route_command("/queue")
            assert "provide a job ID" in handler.route_command("/approve")
            assert "Invalid job ID" in handler.route_command("/reject abc")
            assert "Unknown command" in handler.route_command("/xyz")
    finally:
        session.close()
        engine.dispose()
        reset_engine()
