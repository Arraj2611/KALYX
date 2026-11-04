"""LLMRouter — two-tier Ollama routing with named model support.

Quick tier (deepseek-v4-flash) handles real-time signal generation where
latency matters. Deep tier (kimi-k2.6) handles thorough market analysis,
debate arbitration, and high-stakes decisions. Named models let debate
participants each run a distinct model for genuine multi-model contention.

All calls retry with exponential backoff so transient Ollama hiccups
never surface as agent failures.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class LLMRouter:
    """Route LLM calls to Ollama using a two-tier model hierarchy.

    Config keys
    -----------
    quick_model       : model name for low-latency, real-time calls
    deep_model        : model name for thorough / analytical calls
    ollama_base_url   : base URL for Ollama (default: http://localhost:11434)
    timeout_seconds   : per-request timeout in seconds (default: 120)
    max_retries       : number of attempts before propagating an error (default: 3)
    """

    def __init__(self, config: dict) -> None:
        self._quick_model: str = config["quick_model"]
        self._deep_model: str = config["deep_model"]
        self._base_url: str = config.get("ollama_base_url", "http://localhost:11434")
        self._named_models: dict[str, str] = {}
        self._timeout: float = float(config.get("timeout_seconds", 120))
        self._max_retries: int = int(config.get("max_retries", 3))
        # One client per running event loop, built on first use. Building a client for every call
        # (loading TLS settings) cost about a second a call; a client cannot cross event loops.
        self._http: httpx.AsyncClient | None = None
        self._http_loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_model(self, name: str, model: str) -> None:
        """Register a named model alias for use in multi-model debate.

        Args:
            name:  Logical name (e.g. "bullish", "bearish", "neutral").
            model: Ollama model identifier (e.g. "deepseek-v4-flash").
        """
        self._named_models[name] = model
        logger.debug("Registered named model '%s' -> '%s'", name, model)

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        tier: str = "quick",
    ) -> str:
        """Generate a response using the quick or deep tier model.

        Args:
            prompt:        User-facing prompt text.
            system_prompt: Optional system context for the model.
            tier:          "quick" (default) or "deep".

        Returns:
            Model response as a plain string.
        """
        model = self._deep_model if tier == "deep" else self._quick_model
        return await self._call_ollama(model, prompt, system_prompt)

    async def generate_with_model(
        self,
        prompt: str,
        system_prompt: str,
        model_name: str,
    ) -> str:
        """Generate a response using a previously registered named model.

        Args:
            prompt:        User-facing prompt text.
            system_prompt: System context for the model.
            model_name:    Name registered via :meth:`register_model`.

        Returns:
            Model response as a plain string.

        Raises:
            KeyError: If ``model_name`` has not been registered.
        """
        if model_name not in self._named_models:
            raise KeyError(
                f"Model name '{model_name}' is not registered. "
                f"Call register_model('{model_name}', '<ollama-model>') first."
            )
        model = self._named_models[model_name]
        return await self._call_ollama(model, prompt, system_prompt)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._http is None or self._http_loop is not loop or getattr(self._http, "is_closed", False) is True:
            self._http = httpx.AsyncClient(timeout=self._timeout)
            self._http_loop = loop
        return self._http

    async def aclose(self) -> None:
        """Close the shared HTTP client. A later call builds a new one."""
        client, loop = self._http, self._http_loop
        self._http, self._http_loop = None, None
        if client is not None and loop is asyncio.get_running_loop():
            await client.aclose()

    async def _call_ollama(
        self,
        model: str,
        prompt: str,
        system_prompt: str,
    ) -> str:
        """POST to the Ollama /api/generate endpoint with retry/backoff.

        Retries up to ``_max_retries`` times using exponential backoff
        (2^attempt seconds between attempts). On exhaustion, re-raises
        the last exception.

        Args:
            model:         Ollama model identifier.
            prompt:        Prompt text to send.
            system_prompt: System context string (may be empty).

        Returns:
            The ``response`` field from the Ollama JSON response.
        """
        url = f"{self._base_url}/api/generate"
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "system": system_prompt,
            "stream": False,
        }

        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                response = await self._client().post(url, json=payload)
                response.raise_for_status()
                return response.json()["response"]
            except Exception as exc:
                last_exc = exc
                if attempt < self._max_retries - 1:
                    backoff = 2 ** attempt
                    logger.warning(
                        "Ollama call failed (attempt %d/%d, model=%s): %s — retrying in %ds",
                        attempt + 1,
                        self._max_retries,
                        model,
                        exc,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                else:
                    logger.error(
                        "Ollama call exhausted retries (model=%s): %s",
                        model,
                        exc,
                    )

        raise last_exc  # type: ignore[misc]
