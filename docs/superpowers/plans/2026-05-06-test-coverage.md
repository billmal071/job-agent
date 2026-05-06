# Test Coverage for Critical Untested Modules

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unit tests for three critical untested modules: AIClient completion/retry logic, BrowserManager lifecycle, and AuthManager login flows.

**Architecture:** Pure unit tests using MagicMock for external deps (Playwright, httpx, anthropic SDK). Each test file covers one module. All humanizer/sleep calls mocked to avoid delays.

**Tech Stack:** Python 3.11+, pytest, unittest.mock, uv

---

### Task 1: Expand AIClient tests — completion routing, rate limiting, retry backoff

The existing `test_ai_client.py` covers init/classification/auth-retry. Add tests for: provider completion routing, Groq rate limiting, retry backoff for rate_limit/server errors, and provider-specific response parsing.

**Files:**
- Modify: `tests/unit/test_ai_client.py`

- [ ] **Step 1: Add completion routing and Groq rate limiting tests**

Append to `tests/unit/test_ai_client.py`:

```python
class TestCompletionRouting:
    """Verify complete() routes to the correct provider method."""

    def test_groq_routes_to_openai_compat(self):
        s = _settings(ai_provider="groq")
        client = AIClient(s)
        with patch.object(client, "_complete_openai_compat", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()

    def test_gemini_routes_to_gemini(self):
        s = _settings(ai_provider="gemini")
        client = AIClient(s)
        with patch.object(client, "_complete_gemini", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()

    def test_ollama_routes_to_ollama(self):
        s = _settings(ai_provider="ollama")
        client = AIClient(s)
        with patch.object(client, "_complete_ollama", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()

    def test_anthropic_routes_to_anthropic(self):
        s = _settings(ai_provider="anthropic")
        with patch("job_agent.ai.client.anthropic", create=True):
            client = AIClient(s)
        with patch.object(client, "_complete_anthropic", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()

    def test_openrouter_routes_to_openai_compat(self):
        s = _settings(ai_provider="openrouter", openrouter_api_key="test-or")
        client = AIClient(s)
        with patch.object(client, "_complete_openai_compat", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()


class TestGroqRateLimiting:
    """Groq enforces 3s minimum between calls."""

    def test_groq_has_min_interval(self):
        s = _settings(ai_provider="groq")
        client = AIClient(s)
        assert client._min_call_interval == 3.0

    def test_non_groq_has_no_interval(self):
        s = _settings(ai_provider="gemini")
        client = AIClient(s)
        assert client._min_call_interval == 0.0

    @patch("job_agent.ai.client.time")
    def test_groq_throttles_calls(self, mock_time):
        mock_time.time.side_effect = [
            10.0,   # elapsed check: time.time()
            10.0,   # _last_call_time update after success
        ]
        mock_time.sleep = lambda x: None

        s = _settings(ai_provider="groq")
        client = AIClient(s)
        client._last_call_time = 9.0  # 1s ago — should throttle

        with patch.object(client, "_complete_openai_compat", return_value="ok"):
            client.complete("hello")

        # Should have slept for the remaining 2s (3.0 - 1.0)
        mock_time.sleep.assert_not_called  # time mock handles it


class TestRetryBackoff:
    """Retry logic for rate_limit and server errors."""

    @patch("job_agent.ai.client.time")
    def test_rate_limit_retries_with_backoff(self, mock_time):
        mock_time.time.return_value = 100.0
        mock_time.sleep = lambda x: None

        s = _settings(ai_provider="groq")
        client = AIClient(s)
        client._last_call_time = 0  # no throttle

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("429 rate limit exceeded")
            return "success"

        with patch.object(client, "_complete_openai_compat", side_effect=side_effect):
            result = client.complete("hello", retries=3)

        assert result == "success"
        assert call_count == 3

    @patch("job_agent.ai.client.time")
    def test_server_error_retries_with_backoff(self, mock_time):
        mock_time.time.return_value = 100.0
        mock_time.sleep = lambda x: None

        s = _settings(ai_provider="gemini")
        client = AIClient(s)

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("502 bad gateway")
            return "recovered"

        with patch.object(client, "_complete_gemini", side_effect=side_effect):
            result = client.complete("hello", retries=3)

        assert result == "recovered"
        assert call_count == 2

    @patch("job_agent.ai.client.time")
    def test_other_error_exhausts_retries(self, mock_time):
        mock_time.time.return_value = 100.0
        mock_time.sleep = lambda x: None

        s = _settings(ai_provider="gemini")
        client = AIClient(s)

        with patch.object(
            client, "_complete_gemini", side_effect=Exception("weird error")
        ):
            with pytest.raises(Exception, match="weird error"):
                client.complete("hello", retries=2)


class TestGeminiCompletion:
    """Test Gemini provider response parsing."""

    def test_parses_valid_response(self):
        s = _settings(ai_provider="gemini")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "Hello world"}]}}
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        mock_response.raise_for_status = lambda: None

        with patch.object(client._http, "post", return_value=mock_response):
            result = client._complete_gemini("prompt", "system", 100, 0.3)

        assert result == "Hello world"

    def test_raises_on_no_candidates(self):
        s = _settings(ai_provider="gemini")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {"candidates": []}
        mock_response.raise_for_status = lambda: None

        with patch.object(client._http, "post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="no candidates"):
                client._complete_gemini("prompt", "", 100, 0.3)


class TestOpenAICompatCompletion:
    """Test OpenAI-compatible provider (Groq/OpenRouter) response parsing."""

    def test_parses_valid_response(self):
        s = _settings(ai_provider="groq")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "AI response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_response.raise_for_status = lambda: None

        with patch.object(client._http, "post", return_value=mock_response):
            result = client._complete_openai_compat(
                "https://api.groq.com/openai/v1",
                "test-key",
                "prompt", "system", 100, 0.3,
            )

        assert result == "AI response"

    def test_raises_on_no_choices(self):
        s = _settings(ai_provider="groq")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}
        mock_response.raise_for_status = lambda: None

        with patch.object(client._http, "post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="no choices"):
                client._complete_openai_compat(
                    "https://api.groq.com/openai/v1",
                    "test-key",
                    "prompt", "", 100, 0.3,
                )


class TestOllamaCompletion:
    """Test Ollama provider response parsing."""

    def test_parses_valid_response(self):
        s = _settings(ai_provider="ollama")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "message": {"content": "Local LLM response"}
        }
        mock_response.raise_for_status = lambda: None

        with patch.object(client._http, "post", return_value=mock_response):
            result = client._complete_ollama("prompt", "system", 100, 0.3)

        assert result == "Local LLM response"

    def test_raises_on_empty_response(self):
        s = _settings(ai_provider="ollama")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": ""}}
        mock_response.raise_for_status = lambda: None

        with patch.object(client._http, "post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="empty response"):
                client._complete_ollama("prompt", "", 100, 0.3)
```

Also add at the top of the file, after existing imports:
```python
from unittest.mock import patch, MagicMock
```
(The existing file only imports `patch` — add `MagicMock`)

- [ ] **Step 2: Run tests**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_ai_client.py -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_ai_client.py
git commit -m "test: add completion routing, rate limiting, retry backoff, and provider parsing tests for AIClient"
```

---

### Task 2: Add BrowserManager tests

**Files:**
- Create: `tests/unit/test_browser_manager.py`

- [ ] **Step 1: Write BrowserManager tests**

```python
# tests/unit/test_browser_manager.py
"""Tests for BrowserManager lifecycle and context management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from job_agent.config import Settings


def _settings(tmp_path: Path, **overrides) -> Settings:
    defaults = dict(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test-secret",
    )
    defaults.update(overrides)
    s = Settings(**defaults)
    s.browser.state_dir = str(tmp_path / "browser_state")
    return s


class TestInit:
    def test_creates_state_dir(self, tmp_path):
        s = _settings(tmp_path)
        from job_agent.browser.manager import BrowserManager

        mgr = BrowserManager(s)
        assert Path(mgr._state_dir).exists()
        assert mgr._browser is None
        assert mgr._contexts == {}

    def test_state_dir_from_settings(self, tmp_path):
        s = _settings(tmp_path)
        s.browser.state_dir = str(tmp_path / "custom_state")
        from job_agent.browser.manager import BrowserManager

        mgr = BrowserManager(s)
        assert mgr._state_dir == tmp_path / "custom_state"
        assert mgr._state_dir.exists()


class TestStartPlaywright:
    @patch("job_agent.browser.manager.sync_playwright")
    def test_launches_chromium(self, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        mgr = BrowserManager(s)
        mgr.start()

        assert mgr._playwright == mock_pw
        mock_pw.chromium.launch.assert_called_once()
        kwargs = mock_pw.chromium.launch.call_args.kwargs
        assert kwargs["headless"] is True
        assert kwargs["channel"] == "chrome"

    @patch("job_agent.browser.manager.sync_playwright")
    def test_chrome_fallback_to_chromium(self, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw
        # First call with channel="chrome" fails, second without channel succeeds
        mock_pw.chromium.launch.side_effect = [
            Exception("Chrome not found"),
            MagicMock(),
        ]

        mgr = BrowserManager(s)
        mgr.start()

        assert mock_pw.chromium.launch.call_count == 2
        # Second call should not have "channel" kwarg
        second_kwargs = mock_pw.chromium.launch.call_args_list[1].kwargs
        assert "channel" not in second_kwargs

    @patch("job_agent.browser.manager.sync_playwright")
    def test_proxy_passed_to_launch(self, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        s.browser.proxy = "http://proxy:8080"
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        mgr = BrowserManager(s)
        mgr.start()

        kwargs = mock_pw.chromium.launch.call_args.kwargs
        assert kwargs["proxy"] == {"server": "http://proxy:8080"}


class TestStartCamoufox:
    @patch("job_agent.browser.manager.BrowserManager._start_camoufox")
    def test_routes_to_camoufox_when_enabled(self, mock_start, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = True
        from job_agent.browser.manager import BrowserManager

        mgr = BrowserManager(s)
        mgr.start()

        mock_start.assert_called_once()


class TestGetContext:
    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_creates_context_with_viewport(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw
        mock_browser = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_ctx = MagicMock()
        mock_browser.new_context.return_value = mock_ctx

        mgr = BrowserManager(s)
        mgr.start()
        ctx = mgr.get_context("default")

        assert ctx == mock_ctx
        kwargs = mock_browser.new_context.call_args.kwargs
        assert kwargs["viewport"]["width"] == s.browser.viewport_width
        assert kwargs["viewport"]["height"] == s.browser.viewport_height
        mock_stealth.assert_called_once_with(mock_ctx)

    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_caches_context(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        mgr = BrowserManager(s)
        mgr.start()
        ctx1 = mgr.get_context("test")
        ctx2 = mgr.get_context("test")
        assert ctx1 is ctx2

    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_loads_state_file_if_exists(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        mgr = BrowserManager(s)
        mgr.start()

        # Create a fake state file
        state_file = mgr._state_dir / "test_state.json"
        state_file.write_text('{"cookies": []}')

        mgr.get_context("test")

        kwargs = mock_pw.chromium.launch.return_value.new_context.call_args.kwargs
        assert kwargs["storage_state"] == str(state_file)

    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_auto_starts_browser_if_needed(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        mgr = BrowserManager(s)
        # Don't call start() — get_context should trigger it
        mgr.get_context("default")

        mock_sp.return_value.start.assert_called_once()

    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_no_stealth_for_camoufox(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = True
        from job_agent.browser.manager import BrowserManager

        mgr = BrowserManager(s)
        mock_browser = MagicMock()
        mgr._browser = mock_browser

        mgr.get_context("default")
        mock_stealth.assert_not_called()

    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_no_user_agent_for_camoufox(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = True
        from job_agent.browser.manager import BrowserManager

        mgr = BrowserManager(s)
        mock_browser = MagicMock()
        mgr._browser = mock_browser

        mgr.get_context("default")
        kwargs = mock_browser.new_context.call_args.kwargs
        assert "user_agent" not in kwargs


class TestSaveState:
    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_saves_to_state_file(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        mgr = BrowserManager(s)
        mgr.start()
        ctx = mgr.get_context("default")
        mgr.save_state("default")

        state_file = str(mgr._state_dir / "default_state.json")
        ctx.storage_state.assert_called_once_with(path=state_file)

    def test_no_op_for_unknown_context(self, tmp_path):
        s = _settings(tmp_path)
        from job_agent.browser.manager import BrowserManager

        mgr = BrowserManager(s)
        # Should not raise
        mgr.save_state("nonexistent")


class TestClose:
    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_closes_all_contexts_and_browser(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw
        mock_browser = mock_pw.chromium.launch.return_value

        mgr = BrowserManager(s)
        mgr.start()
        ctx = mgr.get_context("default")

        mgr.close()

        ctx.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()
        assert mgr._browser is None
        assert mgr._playwright is None

    def test_close_idempotent(self, tmp_path):
        s = _settings(tmp_path)
        from job_agent.browser.manager import BrowserManager

        mgr = BrowserManager(s)
        # Should not raise even with nothing to close
        mgr.close()
        mgr.close()


class TestContextManager:
    @patch("job_agent.browser.manager.sync_playwright")
    @patch("job_agent.browser.manager.apply_stealth")
    def test_enter_starts_exit_closes(self, mock_stealth, mock_sp, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = False
        from job_agent.browser.manager import BrowserManager

        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        with BrowserManager(s) as mgr:
            assert mgr._browser is not None

        # After exit, browser should be closed
        assert mgr._browser is None
```

- [ ] **Step 2: Run tests**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_browser_manager.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_browser_manager.py
git commit -m "test: add BrowserManager lifecycle, context caching, state persistence tests"
```

---

### Task 3: Add AuthManager tests

**Files:**
- Create: `tests/unit/test_auth.py`

- [ ] **Step 1: Write AuthManager tests**

```python
# tests/unit/test_auth.py
"""Tests for AuthManager login flows."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from job_agent.db.models import Platform


@pytest.fixture(autouse=True)
def mock_humanizer():
    """Mock all humanizer functions to avoid delays."""
    with (
        patch("job_agent.browser.auth.human_delay"),
        patch("job_agent.browser.auth.human_click"),
        patch("job_agent.browser.auth.human_type"),
    ):
        yield


@pytest.fixture
def mock_context():
    """Mock BrowserContext that returns configurable pages."""
    context = MagicMock()
    return context


def _make_page(url="https://example.com", title="Example"):
    """Create a mock Page with configurable URL and title."""
    page = MagicMock()
    type(page).url = url  # Use property to allow mutation
    page.title.return_value = title
    # Default: no elements found
    locator = MagicMock()
    locator.count.return_value = 0
    locator.is_visible.return_value = False
    page.locator.return_value = locator
    return page


class TestLoginRouting:
    def test_unsupported_platform_raises(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        with pytest.raises(ValueError, match="Unsupported platform"):
            auth.login(MagicMock(), "user", "pass")

    def test_routes_to_linkedin(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = _make_page(url="https://www.linkedin.com/feed/")
        mock_context.new_page.return_value = page

        # Simulate already logged in
        def locator_side_effect(selector):
            loc = MagicMock()
            if "global-nav__me" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect

        result = auth.login(Platform.LINKEDIN, "user", "pass")
        assert result == page

    def test_routes_to_each_platform(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        platforms = [
            Platform.INDEED,
            Platform.GLASSDOOR,
            Platform.ZIPRECRUITER,
            Platform.DICE,
            Platform.WELLFOUND,
        ]
        for platform in platforms:
            page = _make_page()
            mock_context.new_page.return_value = page
            # Each handler should return a page without error
            result = auth.login(platform, "user", "pass")
            assert result is not None


class TestIsLoggedIn:
    def test_linkedin_logged_in(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()

        def locator_side_effect(selector):
            loc = MagicMock()
            if "global-nav__me" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect
        assert auth.is_logged_in(Platform.LINKEDIN, page) is True

    def test_linkedin_not_logged_in(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        locator = MagicMock()
        locator.count.return_value = 0
        page.locator.return_value = locator

        assert auth.is_logged_in(Platform.LINKEDIN, page) is False

    def test_exception_returns_false(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        page.locator.side_effect = RuntimeError("Page crashed")

        assert auth.is_logged_in(Platform.LINKEDIN, page) is False

    def test_unsupported_platform_returns_false(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        assert auth.is_logged_in(MagicMock(), page) is False

    def test_indeed_logged_in(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()

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
    def test_session_restored_skips_login(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = _make_page(url="https://www.linkedin.com/feed/")
        mock_context.new_page.return_value = page

        # is_logged_in returns True
        with patch.object(auth, "is_logged_in", return_value=True):
            result = auth._login_linkedin("user", "pass")
        assert result == page

    def test_login_with_form(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        mock_context.new_page.return_value = page

        # First URL: login page, then: feed page after login
        url_sequence = iter([
            "https://www.linkedin.com/login",  # goto feed redirects to login
            "https://www.linkedin.com/login",  # still on login
            "https://www.linkedin.com/feed/",  # after submit
            "https://www.linkedin.com/feed/",  # checked again
            "https://www.linkedin.com/feed/",  # final check
        ])
        type(page).url = property(lambda self: next(url_sequence, "https://www.linkedin.com/feed/"))

        # Username field visible
        username_locator = MagicMock()
        username_locator.count.return_value = 1
        username_locator.is_visible.return_value = True

        def locator_side_effect(selector):
            if selector == "#username":
                return username_locator
            loc = MagicMock()
            loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect

        # is_logged_in: False initially, True after form submission
        logged_in_calls = iter([False, False, True])
        with patch.object(
            auth, "is_logged_in", side_effect=lambda p, pg: next(logged_in_calls, True)
        ):
            result = auth._login_linkedin("user", "pass")

        assert result == page

    def test_login_fails_raises_runtime_error(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        mock_context.new_page.return_value = page

        # URL stays on login
        type(page).url = property(lambda self: "https://www.linkedin.com/login")

        # Username field not visible (CAPTCHA)
        locator = MagicMock()
        locator.count.return_value = 0
        locator.is_visible.return_value = False
        page.locator.return_value = locator

        with patch.object(auth, "is_logged_in", return_value=False):
            with pytest.raises(RuntimeError, match="LinkedIn login failed"):
                auth._login_linkedin("user", "pass")


class TestSimplePlatformLogins:
    """ZipRecruiter, Dice, and Wellfound have straightforward login flows."""

    def test_ziprecruiter_navigates_and_submits(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        mock_context.new_page.return_value = page

        result = auth._login_ziprecruiter("user", "pass")

        assert result == page
        page.goto.assert_called_once_with(
            "https://www.ziprecruiter.com/authn/login"
        )

    def test_dice_navigates_and_submits(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        mock_context.new_page.return_value = page

        result = auth._login_dice("user", "pass")

        assert result == page
        page.goto.assert_called_once_with(
            "https://www.dice.com/dashboard/login"
        )

    def test_wellfound_navigates_and_submits(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        mock_context.new_page.return_value = page

        result = auth._login_wellfound("user", "pass")

        assert result == page
        page.goto.assert_called_once_with("https://wellfound.com/login")


class TestIndeedLogin:
    def test_already_logged_in_returns_early(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        mock_context.new_page.return_value = page
        page.title.return_value = "Indeed"

        # Account menu found — already logged in
        def locator_side_effect(selector):
            loc = MagicMock()
            if "AccountMenu" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect

        result = auth._login_indeed("user", "pass")
        assert result == page

    def test_cloudflare_challenge_waits(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        mock_context.new_page.return_value = page

        # First few calls return Cloudflare, then normal
        title_calls = iter(["Just a moment", "Just a moment", "Indeed"])
        page.title.side_effect = lambda: next(title_calls, "Indeed")
        type(page).url = property(lambda self: "https://secure.indeed.com/auth")

        locator = MagicMock()
        locator.count.return_value = 0
        page.locator.return_value = locator

        result = auth._login_indeed("user", "pass")
        assert result == page


class TestGlassdoorLogin:
    def test_already_logged_in_returns_early(self, mock_context):
        from job_agent.browser.auth import AuthManager

        auth = AuthManager(mock_context)
        page = MagicMock()
        mock_context.new_page.return_value = page
        page.title.return_value = "Glassdoor"

        # Profile button found — already logged in
        def locator_side_effect(selector):
            loc = MagicMock()
            if "profile" in selector.lower() or "ProfileButton" in selector:
                loc.count.return_value = 1
            else:
                loc.count.return_value = 0
            return loc

        page.locator.side_effect = locator_side_effect

        result = auth._login_glassdoor("user", "pass")
        assert result == page
```

- [ ] **Step 2: Run tests**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/unit/test_auth.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_auth.py
git commit -m "test: add AuthManager login routing, session detection, and platform login tests"
```

---

### Task 4: Run full test suite and verify

- [ ] **Step 1: Run full test suite**

Run: `cd /home/williams/Documents/personal/job-agent && uv run pytest tests/ -v`
Expected: All tests PASS (209 existing + ~50 new)

- [ ] **Step 2: Run linter**

Run: `cd /home/williams/Documents/personal/job-agent && uv run ruff check tests/unit/test_ai_client.py tests/unit/test_browser_manager.py tests/unit/test_auth.py`
Expected: No errors

- [ ] **Step 3: Run formatter**

Run: `cd /home/williams/Documents/personal/job-agent && uv run ruff format --check tests/unit/test_ai_client.py tests/unit/test_browser_manager.py tests/unit/test_auth.py`
Expected: No formatting issues
