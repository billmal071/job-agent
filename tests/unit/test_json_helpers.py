"""Tests for JSON parsing helper."""

from job_agent.utils.json_helpers import parse_json_list


class TestParseJsonList:
    def test_valid_json_list(self):
        assert parse_json_list('["Python", "Go"]') == ["Python", "Go"]

    def test_none_returns_default(self):
        assert parse_json_list(None) == []

    def test_empty_string_returns_default(self):
        assert parse_json_list("") == []

    def test_invalid_json_returns_default(self):
        assert parse_json_list("not json") == []

    def test_json_object_returns_default(self):
        assert parse_json_list('{"key": "val"}') == []

    def test_custom_default(self):
        assert parse_json_list(None, default=["fallback"]) == ["fallback"]
