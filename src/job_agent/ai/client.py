"""Multi-provider AI client with retry logic.

Supports: Anthropic Claude, Google Gemini, Groq, OpenRouter, Ollama (local).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from job_agent.config import Settings
from job_agent.utils.logging import get_logger

log = get_logger(__name__)

# Provider constants
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_GEMINI = "gemini"
PROVIDER_GROQ = "groq"
PROVIDER_OPENROUTER = "openrouter"
PROVIDER_OLLAMA = "ollama"

# Default models per provider
DEFAULT_MODELS = {
    PROVIDER_ANTHROPIC: "claude-sonnet-4-20250514",
    PROVIDER_GEMINI: "gemini-2.0-flash",
    PROVIDER_GROQ: "llama-3.3-70b-versatile",
    PROVIDER_OPENROUTER: "google/gemini-2.0-flash-exp:free",
    PROVIDER_OLLAMA: "llama3.1",
}

# API base URLs
API_URLS = {
    PROVIDER_GEMINI: "https://generativelanguage.googleapis.com/v1beta",
    PROVIDER_GROQ: "https://api.groq.com/openai/v1",
    PROVIDER_OPENROUTER: "https://openrouter.ai/api/v1",
    PROVIDER_OLLAMA: "http://localhost:11434",  # overridden by settings.ollama_url
}


class AIClient:
    """Multi-provider AI client with retry and error handling.

    Supports Anthropic Claude, Google Gemini, Groq, OpenRouter, and Ollama.
    Configure via settings or environment variables:
        - JOB_AGENT_AI_PROVIDER: anthropic|gemini|groq|openrouter|ollama
        - JOB_AGENT_ANTHROPIC_API_KEY: for Anthropic
        - JOB_AGENT_GEMINI_API_KEY: for Google Gemini
        - JOB_AGENT_GROQ_API_KEY: for Groq
        - JOB_AGENT_OPENROUTER_API_KEY: for OpenRouter
        - Ollama requires no API key (runs locally)
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = settings.ai_provider
        self.model = settings.matching.model or DEFAULT_MODELS.get(
            self.provider, DEFAULT_MODELS[PROVIDER_GEMINI]
        )
        self._http = httpx.Client(timeout=60)
        self._last_call_time: float = 0
        # Groq free tier: 30 req/min + daily token limits. Space calls to avoid 429s.
        self._min_call_interval: float = 3.0 if self.provider == PROVIDER_GROQ else 0.0

        # Guard against model-provider mismatch
        if "claude" in self.model.lower() and self.provider != PROVIDER_ANTHROPIC:
            default = DEFAULT_MODELS.get(self.provider, DEFAULT_MODELS[PROVIDER_GEMINI])
            log.warning(
                "model_provider_mismatch",
                model=self.model,
                provider=self.provider,
                fallback=default,
            )
            self.model = default

        # Validate provider config
        if self.provider == PROVIDER_ANTHROPIC:
            if not settings.anthropic_api_key:
                raise ValueError(
                    "Anthropic API key required. Set JOB_AGENT_ANTHROPIC_API_KEY env var."
                )
            import anthropic

            self._anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        elif self.provider == PROVIDER_GEMINI:
            if not settings.gemini_api_key:
                raise ValueError(
                    "Gemini API key required. Get a free key at https://aistudio.google.com/apikey\n"
                    "Set JOB_AGENT_GEMINI_API_KEY env var."
                )
        elif self.provider == PROVIDER_GROQ:
            if not settings.groq_api_key:
                raise ValueError(
                    "Groq API key required. Get a free key at https://console.groq.com\n"
                    "Set JOB_AGENT_GROQ_API_KEY env var."
                )
        elif self.provider == PROVIDER_OPENROUTER:
            if not settings.openrouter_api_key:
                raise ValueError(
                    "OpenRouter API key required. Get one at https://openrouter.ai/keys\n"
                    "Set JOB_AGENT_OPENROUTER_API_KEY env var."
                )
        elif self.provider == PROVIDER_OLLAMA:
            pass  # No API key needed
        else:
            raise ValueError(
                f"Unknown AI provider: {self.provider}. "
                f"Supported: {PROVIDER_ANTHROPIC}, {PROVIDER_GEMINI}, {PROVIDER_GROQ}, "
                f"{PROVIDER_OPENROUTER}, {PROVIDER_OLLAMA}"
            )

        # Use configurable Ollama URL
        if self.provider == PROVIDER_OLLAMA and settings.ollama_url:
            self._ollama_url = settings.ollama_url
        else:
            self._ollama_url = API_URLS[PROVIDER_OLLAMA]

        log.info("ai_client_init", provider=self.provider, model=self.model)

    def complete(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.3,
        retries: int = 3,
    ) -> str:
        """Send a completion request with retry logic."""
        # Throttle requests to avoid rate limits on free tiers
        if self._min_call_interval > 0:
            elapsed = time.time() - self._last_call_time
            if elapsed < self._min_call_interval:
                time.sleep(self._min_call_interval - elapsed)

        for attempt in range(retries):
            try:
                result: str
                if self.provider == PROVIDER_ANTHROPIC:
                    result = self._complete_anthropic(
                        prompt, system, max_tokens, temperature
                    )
                elif self.provider == PROVIDER_GEMINI:
                    result = self._complete_gemini(
                        prompt, system, max_tokens, temperature
                    )
                elif self.provider == PROVIDER_GROQ:
                    result = self._complete_openai_compat(
                        API_URLS[PROVIDER_GROQ],
                        self.settings.groq_api_key,
                        prompt,
                        system,
                        max_tokens,
                        temperature,
                    )
                elif self.provider == PROVIDER_OPENROUTER:
                    result = self._complete_openai_compat(
                        API_URLS[PROVIDER_OPENROUTER],
                        self.settings.openrouter_api_key,
                        prompt,
                        system,
                        max_tokens,
                        temperature,
                    )
                elif self.provider == PROVIDER_OLLAMA:
                    result = self._complete_ollama(
                        prompt, system, max_tokens, temperature
                    )
                else:
                    raise ValueError(f"Unknown provider: {self.provider}")
                self._last_call_time = time.time()
                return result
            except Exception as e:
                err_str = str(e).lower()
                err_class = self._classify_error(err_str)

                if err_class == "auth":
                    log.error("ai_auth_error", error=str(e))
                    raise
                elif err_class == "rate_limit":
                    wait = 2 ** (attempt + 1)
                    log.warning("ai_rate_limited", wait=wait, attempt=attempt + 1)
                    time.sleep(wait)
                elif err_class == "server":
                    wait = 2**attempt
                    log.warning("ai_server_error", wait=wait, attempt=attempt + 1)
                    time.sleep(wait)
                else:
                    log.error("ai_api_error", error=str(e), attempt=attempt + 1)
                    if attempt == retries - 1:
                        raise
                    time.sleep(1)

        raise RuntimeError("AI completion failed after retries")

    @staticmethod
    def _classify_error(err_str: str) -> str:
        """Classify an API error for retry decisions."""
        if (
            "401" in err_str
            or "403" in err_str
            or "unauthorized" in err_str
            or "forbidden" in err_str
        ):
            return "auth"
        if "rate" in err_str or "429" in err_str:
            return "rate_limit"
        if (
            "500" in err_str
            or "502" in err_str
            or "503" in err_str
            or "server" in err_str
        ):
            return "server"
        return "other"

    def _complete_anthropic(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> str:
        """Complete using Anthropic Claude API."""

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system

        response = self._anthropic.messages.create(**kwargs)
        text = response.content[0].text
        log.debug(
            "ai_completion",
            provider="anthropic",
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return text

    def _complete_gemini(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> str:
        """Complete using Google Gemini API."""
        url = (
            f"{API_URLS[PROVIDER_GEMINI]}/models/{self.model}:generateContent"
            f"?key={self.settings.gemini_api_key}"
        )

        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": system}]})
            contents.append(
                {
                    "role": "model",
                    "parts": [
                        {"text": "Understood. I will follow these instructions."}
                    ],
                }
            )
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        resp = self._http.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates")
        if not candidates:
            raise RuntimeError(
                f"Gemini returned no candidates: {data.get('promptFeedback', data)}"
            )
        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if not text:
            raise RuntimeError(f"Gemini returned empty response: {candidates[0]}")
        usage = data.get("usageMetadata", {})
        log.debug(
            "ai_completion",
            provider="gemini",
            model=self.model,
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
        )
        return text

    def _complete_openai_compat(
        self,
        base_url: str,
        api_key: str,
        prompt: str,
        system: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Complete using OpenAI-compatible API (Groq, OpenRouter, etc.)."""
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        resp = self._http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices")
        if not choices:
            raise RuntimeError(f"API returned no choices: {data.get('error', data)}")
        text = choices[0].get("message", {}).get("content", "")
        if not text:
            raise RuntimeError(f"API returned empty response: {choices[0]}")
        usage = data.get("usage", {})
        log.debug(
            "ai_completion",
            provider=self.provider,
            model=self.model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
        return text

    def _complete_ollama(
        self, prompt: str, system: str, max_tokens: int, temperature: float
    ) -> str:
        """Complete using local Ollama instance."""
        url = f"{self._ollama_url}/api/chat"

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }

        timeout = self.settings.agent.ollama_request_timeout
        resp = self._http.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        text = data.get("message", {}).get("content", "")
        if not text:
            raise RuntimeError(f"Ollama returned empty response: {data}")
        log.debug(
            "ai_completion",
            provider="ollama",
            model=self.model,
        )
        return text
