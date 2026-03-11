"""Tests for proxy configuration wiring."""

from __future__ import annotations

from job_agent.config import BrowserConfig, Settings


def test_proxy_url_wires_to_browser_proxy():
    """Top-level proxy_url flows into browser.proxy when browser.proxy is unset."""
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
        proxy_url="http://proxy.example.com:8080",
    )
    assert settings.browser.proxy == "http://proxy.example.com:8080"


def test_browser_proxy_takes_precedence():
    """Explicit browser.proxy is not overridden by proxy_url."""
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
        proxy_url="http://proxy.example.com:8080",
        browser=BrowserConfig(proxy="http://direct-proxy:3128"),
    )
    assert settings.browser.proxy == "http://direct-proxy:3128"


def test_no_proxy_when_not_set():
    """Browser proxy stays None when neither proxy_url nor browser.proxy is set."""
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    assert settings.browser.proxy is None
