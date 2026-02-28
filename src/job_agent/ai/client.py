"""Anthropic SDK wrapper with retry logic."""

from __future__ import annotations

import time
from typing import Any

import anthropic

from job_agent.config import Settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)


class AIClient:
    """Wrapper around the Anthropic API with retry and error handling."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.matching.model

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        retries: int = 3,
    ) -> str:
        """Send a completion request with retry logic."""
        messages = [{"role": "user", "content": prompt}]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        for attempt in range(retries):
            try:
                response = self.client.messages.create(**kwargs)
                text = response.content[0].text
                log.debug(
                    "ai_completion",
                    model=self.model,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
                return text
            except anthropic.RateLimitError:
                wait = 2 ** (attempt + 1)
                log.warning("ai_rate_limited", wait=wait, attempt=attempt + 1)
                time.sleep(wait)
            except anthropic.APIError as e:
                log.error("ai_api_error", error=str(e), attempt=attempt + 1)
                if attempt == retries - 1:
                    raise
                time.sleep(1)

        raise RuntimeError("AI completion failed after retries")
