"""Shared JSON parsing utilities."""

from __future__ import annotations

import json


def parse_json_list(raw: str | None, *, default: list | None = None) -> list:
    """Parse a JSON string expected to be a list. Returns default on failure."""
    if default is None:
        default = []
    if not raw:
        return list(default)
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        return list(default)
    except (json.JSONDecodeError, TypeError, ValueError):
        return list(default)
