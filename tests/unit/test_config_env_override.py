"""Tests for environment variable override of YAML config values."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import patch


from job_agent.config import Settings, _strip_env_overridden_keys, load_settings


class TestStripEnvOverriddenKeys:
    def test_removes_top_level_key_with_env_var(self):
        yaml_data = {"ai_provider": "gemini", "flask_secret_key": "test"}
        with patch.dict(os.environ, {"JOB_AGENT_AI_PROVIDER": "groq"}):
            result = _strip_env_overridden_keys(yaml_data)
        assert "ai_provider" not in result
        assert result["flask_secret_key"] == "test"

    def test_removes_nested_key_with_env_var(self):
        yaml_data = {"agent": {"activity_start_hour": 8, "dry_run": False}}
        with patch.dict(os.environ, {"JOB_AGENT_AGENT__ACTIVITY_START_HOUR": "0"}):
            result = _strip_env_overridden_keys(yaml_data)
        assert result["agent"]["dry_run"] is False
        assert "activity_start_hour" not in result["agent"]

    def test_preserves_all_keys_without_env(self):
        yaml_data = {"agent": {"activity_start_hour": 8, "dry_run": False}}
        with patch.dict(os.environ, {}, clear=False):
            # Ensure our test keys aren't set
            env = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("JOB_AGENT_AGENT__")
            }
            with patch.dict(os.environ, env, clear=True):
                result = _strip_env_overridden_keys(yaml_data)
        assert result == yaml_data

    def test_deeply_nested_env_override(self):
        yaml_data = {"browser": {"headless": True, "use_camoufox": True}}
        with patch.dict(os.environ, {"JOB_AGENT_BROWSER__HEADLESS": "false"}):
            result = _strip_env_overridden_keys(yaml_data)
        assert "headless" not in result["browser"]
        assert result["browser"]["use_camoufox"] is True


class TestLoadSettingsEnvOverride:
    def test_env_var_overrides_yaml(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            textwrap.dedent("""\
            agent:
              activity_start_hour: 8
              activity_end_hour: 23
        """)
        )
        # Patch default.yaml to not exist, use our custom config
        with (
            patch.dict(
                os.environ,
                {"JOB_AGENT_AGENT__ACTIVITY_START_HOUR": "0"},
            ),
            patch("job_agent.config.Path") as mock_path_cls,
        ):
            # Make default.yaml not exist
            mock_default = mock_path_cls.return_value
            mock_default.exists.return_value = False

            # But make our override path work normally
            mock_path_cls.side_effect = lambda x: Path(x)

            settings = load_settings(str(yaml_file))
        assert settings.agent.activity_start_hour == 0
        assert settings.agent.activity_end_hour == 23


class TestDotenvOverride:
    """Values defined only in .env must override YAML, like process env vars."""

    def _write_config(self, tmp_path):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "default.yaml").write_text(
            textwrap.dedent("""\
            matching:
              model: ""
            """)
        )

    def test_dotenv_only_value_overrides_yaml(self, tmp_path, monkeypatch):
        self._write_config(tmp_path)
        (tmp_path / ".env").write_text("JOB_AGENT_MATCHING__MODEL=from-dotenv\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("JOB_AGENT_MATCHING__MODEL", raising=False)

        settings = load_settings()
        assert settings.matching.model == "from-dotenv"

    def test_process_env_wins_over_dotenv_and_yaml(self, tmp_path, monkeypatch):
        self._write_config(tmp_path)
        (tmp_path / ".env").write_text("JOB_AGENT_MATCHING__MODEL=from-dotenv\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("JOB_AGENT_MATCHING__MODEL", "from-process-env")

        settings = load_settings()
        assert settings.matching.model == "from-process-env"

    def test_missing_dotenv_file_keeps_yaml_value(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "default.yaml").write_text(
            textwrap.dedent("""\
            matching:
              model: "from-yaml"
            """)
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("JOB_AGENT_MATCHING__MODEL", raising=False)

        settings = load_settings()
        assert settings.matching.model == "from-yaml"


class TestNewConfigFields:
    def test_ollama_url_default(self):
        s = Settings()
        assert s.ollama_url == "http://localhost:11434"

    def test_agent_timeout_defaults(self):
        s = Settings()
        assert s.agent.ai_request_timeout == 60
        assert s.agent.ollama_request_timeout == 120

    def test_browser_viewport_defaults(self):
        s = Settings()
        assert s.browser.viewport_width == 1920
        assert s.browser.viewport_height == 1080

    def test_custom_viewport(self):
        s = Settings(browser={"viewport_width": 1280, "viewport_height": 720})
        assert s.browser.viewport_width == 1280
        assert s.browser.viewport_height == 720
