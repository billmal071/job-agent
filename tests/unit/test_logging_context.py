"""Tests for structured logging context propagation."""

from __future__ import annotations

import structlog

from job_agent.utils.logging import bind_contextvars, clear_contextvars, unbind_contextvars


class TestBindContextvars:
    def test_bind_adds_to_context(self):
        clear_contextvars()
        bind_contextvars(run_id=42, platform="linkedin")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["run_id"] == 42
        assert ctx["platform"] == "linkedin"
        clear_contextvars()

    def test_bind_overwrites_existing(self):
        clear_contextvars()
        bind_contextvars(platform="linkedin")
        bind_contextvars(platform="indeed")
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["platform"] == "indeed"
        clear_contextvars()

    def test_bind_preserves_other_keys(self):
        clear_contextvars()
        bind_contextvars(run_id=1)
        bind_contextvars(job_id=99)
        ctx = structlog.contextvars.get_contextvars()
        assert ctx["run_id"] == 1
        assert ctx["job_id"] == 99
        clear_contextvars()


class TestUnbindContextvars:
    def test_unbind_removes_keys(self):
        clear_contextvars()
        bind_contextvars(run_id=1, platform="linkedin")
        unbind_contextvars("platform")
        ctx = structlog.contextvars.get_contextvars()
        assert "platform" not in ctx
        assert ctx["run_id"] == 1
        clear_contextvars()


class TestClearContextvars:
    def test_clear_removes_all(self):
        bind_contextvars(run_id=1, platform="linkedin", job_id=42)
        clear_contextvars()
        ctx = structlog.contextvars.get_contextvars()
        assert ctx == {}
