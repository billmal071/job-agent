"""Tests for BrowserManager lifecycle and context management."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from job_agent.config import Settings
from job_agent.browser.manager import BrowserManager


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
    s.browser.use_camoufox = False  # default to standard playwright in tests
    return s


# ---------------------------------------------------------------------------
# TestInit
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_state_dir(self, tmp_path):
        s = _settings(tmp_path)
        BrowserManager(s)
        assert Path(s.browser.state_dir).exists()

    def test_state_dir_from_settings(self, tmp_path):
        custom_dir = tmp_path / "custom_state"
        s = _settings(tmp_path)
        s.browser.state_dir = str(custom_dir)
        mgr = BrowserManager(s)
        assert custom_dir.exists()
        assert mgr._state_dir == custom_dir


# ---------------------------------------------------------------------------
# TestStartPlaywright
# ---------------------------------------------------------------------------


class TestStartPlaywright:
    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_launches_chromium(self, mock_sp, mock_stealth, tmp_path):
        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        mgr._start_playwright()

        mock_pw.chromium.launch.assert_called_once()
        call_kwargs = mock_pw.chromium.launch.call_args[1]
        assert call_kwargs["headless"] is True
        assert call_kwargs["channel"] == "chrome"

    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_chrome_fallback_to_chromium(self, mock_sp, mock_stealth, tmp_path):
        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        # First launch (with channel) raises, second succeeds
        fallback_browser = MagicMock()
        mock_pw.chromium.launch.side_effect = [
            Exception("chrome not found"),
            fallback_browser,
        ]

        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        mgr._start_playwright()

        assert mock_pw.chromium.launch.call_count == 2
        # Second call should not have channel
        second_kwargs = mock_pw.chromium.launch.call_args_list[1][1]
        assert "channel" not in second_kwargs
        assert mgr._browser is fallback_browser

    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_proxy_passed_to_launch(self, mock_sp, mock_stealth, tmp_path):
        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        s = _settings(tmp_path)
        s.browser.proxy = "http://myproxy:8080"
        mgr = BrowserManager(s)
        mgr._start_playwright()

        call_kwargs = mock_pw.chromium.launch.call_args[1]
        assert call_kwargs["proxy"] == {"server": "http://myproxy:8080"}


# ---------------------------------------------------------------------------
# TestStartCamoufox
# ---------------------------------------------------------------------------


class TestStartCamoufox:
    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_routes_to_camoufox_when_enabled(self, mock_sp, mock_stealth, tmp_path):
        s = _settings(tmp_path)
        s.browser.use_camoufox = True

        mgr = BrowserManager(s)
        mgr._start_camoufox = MagicMock()
        mgr.start()

        mgr._start_camoufox.assert_called_once()
        mock_sp.assert_not_called()


# ---------------------------------------------------------------------------
# TestGetContext
# ---------------------------------------------------------------------------


class TestGetContext:
    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_creates_context_with_viewport(self, mock_sp, mock_stealth, tmp_path):
        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw
        mock_browser = mock_pw.chromium.launch.return_value

        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        mgr._browser = mock_browser

        mgr.get_context("default")

        call_kwargs = mock_browser.new_context.call_args[1]
        assert call_kwargs["viewport"] == {
            "width": s.browser.viewport_width,
            "height": s.browser.viewport_height,
        }
        assert call_kwargs["locale"] == "en-US"
        assert call_kwargs["timezone_id"] == "America/New_York"

    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_caches_context(self, mock_sp, mock_stealth, tmp_path):
        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw
        mock_browser = mock_pw.chromium.launch.return_value

        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        mgr._browser = mock_browser

        ctx1 = mgr.get_context("default")
        ctx2 = mgr.get_context("default")

        assert ctx1 is ctx2
        assert mock_browser.new_context.call_count == 1

    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_loads_state_file_if_exists(self, mock_sp, mock_stealth, tmp_path):
        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw
        mock_browser = mock_pw.chromium.launch.return_value

        s = _settings(tmp_path)
        state_dir = Path(s.browser.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "myctx_state.json"
        state_file.write_text(json.dumps({"cookies": [], "origins": []}))

        mgr = BrowserManager(s)
        mgr._browser = mock_browser
        mgr.get_context("myctx")

        call_kwargs = mock_browser.new_context.call_args[1]
        assert call_kwargs["storage_state"] == str(state_file)

    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_auto_starts_browser_if_needed(self, mock_sp, mock_stealth, tmp_path):
        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        # Do NOT set _browser — get_context should trigger start()

        mgr.get_context("default")

        # sync_playwright was called to start the browser
        mock_sp.assert_called_once()
        mock_pw.chromium.launch.assert_called_once()

    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_no_stealth_for_camoufox(self, mock_sp, mock_stealth, tmp_path):
        mock_browser = MagicMock()

        s = _settings(tmp_path)
        s.browser.use_camoufox = True
        mgr = BrowserManager(s)
        mgr._browser = mock_browser

        mgr.get_context("default")

        mock_stealth.assert_not_called()

    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_no_user_agent_for_camoufox(self, mock_sp, mock_stealth, tmp_path):
        mock_browser = MagicMock()

        s = _settings(tmp_path)
        s.browser.use_camoufox = True
        mgr = BrowserManager(s)
        mgr._browser = mock_browser

        mgr.get_context("default")

        call_kwargs = mock_browser.new_context.call_args[1]
        assert "user_agent" not in call_kwargs


# ---------------------------------------------------------------------------
# TestSaveState
# ---------------------------------------------------------------------------


class TestSaveState:
    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_saves_to_state_file(self, mock_sp, mock_stealth, tmp_path):
        mock_browser = MagicMock()
        mock_context = MagicMock()

        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        mgr._browser = mock_browser
        mgr._contexts["default"] = mock_context

        mgr.save_state("default")

        expected_path = str(mgr._state_dir / "default_state.json")
        mock_context.storage_state.assert_called_once_with(path=expected_path)

    def test_no_op_for_unknown_context(self, tmp_path):
        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        # Should not raise even if context doesn't exist
        mgr.save_state("nonexistent")


# ---------------------------------------------------------------------------
# TestClose
# ---------------------------------------------------------------------------


class TestClose:
    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_closes_all_contexts_and_browser(self, mock_sp, mock_stealth, tmp_path):
        mock_pw_instance = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw_instance
        mock_browser = MagicMock()
        mock_context = MagicMock()

        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        mgr._playwright = mock_pw_instance
        mgr._browser = mock_browser
        mgr._contexts["default"] = mock_context

        mgr.close()

        mock_context.storage_state.assert_called_once()  # save_state called
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_pw_instance.stop.assert_called_once()

    def test_close_idempotent(self, tmp_path):
        s = _settings(tmp_path)
        mgr = BrowserManager(s)
        # No browser started — should not raise on multiple close() calls
        mgr.close()
        mgr.close()


# ---------------------------------------------------------------------------
# TestContextManager
# ---------------------------------------------------------------------------


class TestContextManager:
    @patch("job_agent.browser.manager.apply_stealth")
    @patch("job_agent.browser.manager.sync_playwright")
    def test_enter_starts_exit_closes(self, mock_sp, mock_stealth, tmp_path):
        mock_pw = MagicMock()
        mock_sp.return_value.start.return_value = mock_pw

        s = _settings(tmp_path)
        mgr = BrowserManager(s)

        with (
            patch.object(mgr, "start", wraps=mgr.start) as mock_start,
            patch.object(mgr, "close", wraps=mgr.close) as mock_close,
        ):
            with mgr:
                mock_start.assert_called_once()
            mock_close.assert_called_once()
