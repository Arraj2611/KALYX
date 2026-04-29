"""Tests for LLMRouter — two-tier Ollama routing with named model support."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call

from app.agents.llm_router import LLMRouter


# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "quick_model": "deepseek-v4-flash",
    "deep_model": "kimi-k2.6",
    "ollama_base_url": "http://localhost:11434",
    "timeout_seconds": 30,
    "max_retries": 3,
}


def make_mock_response(text: str = "Test LLM output") -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": text}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_router_creation():
    """Verify quick_model and deep_model are stored from config."""
    router = LLMRouter(DEFAULT_CONFIG)

    assert router._quick_model == "deepseek-v4-flash"
    assert router._deep_model == "kimi-k2.6"
    assert router._base_url == "http://localhost:11434"
    assert router._timeout == 30.0
    assert router._max_retries == 3
    assert router._named_models == {}


@pytest.mark.asyncio
async def test_generate_quick_tier():
    """generate(prompt, tier='quick') calls Ollama with quick_model."""
    router = LLMRouter(DEFAULT_CONFIG)
    mock_resp = make_mock_response()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await router.generate("What is the market trend?", tier="quick")

    assert result == "Test LLM output"
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
    assert body["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_generate_deep_tier():
    """generate(prompt, tier='deep') calls Ollama with deep_model."""
    router = LLMRouter(DEFAULT_CONFIG)
    mock_resp = make_mock_response()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await router.generate("Analyse RELIANCE deeply.", tier="deep")

    assert result == "Test LLM output"
    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
    assert body["model"] == "kimi-k2.6"


@pytest.mark.asyncio
async def test_generate_with_system_prompt():
    """System prompt is included in the request body sent to Ollama."""
    router = LLMRouter(DEFAULT_CONFIG)
    mock_resp = make_mock_response()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        await router.generate(
            "Buy or sell?",
            system_prompt="You are a trading analyst.",
            tier="quick",
        )

    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
    assert body["system"] == "You are a trading analyst."
    assert body["prompt"] == "Buy or sell?"
    assert body["stream"] is False


def test_register_named_model():
    """register_model stores name -> model in _named_models."""
    router = LLMRouter(DEFAULT_CONFIG)

    router.register_model("bullish", "deepseek-v4-flash")

    assert "bullish" in router._named_models
    assert router._named_models["bullish"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_generate_with_named_model():
    """generate_with_model uses the registered model name for the Ollama call."""
    router = LLMRouter(DEFAULT_CONFIG)
    router.register_model("bullish", "deepseek-v4-flash")
    mock_resp = make_mock_response()

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await router.generate_with_model(
            "Is RELIANCE bullish?",
            system_prompt="You are a bull market analyst.",
            model_name="bullish",
        )

    assert result == "Test LLM output"
    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["json"]
    assert body["model"] == "deepseek-v4-flash"


@pytest.mark.asyncio
async def test_generate_unknown_model_raises():
    """generate_with_model raises KeyError for an unregistered model name."""
    router = LLMRouter(DEFAULT_CONFIG)

    with pytest.raises(KeyError):
        await router.generate_with_model(
            "Some prompt",
            system_prompt="",
            model_name="bearish",  # never registered
        )


@pytest.mark.asyncio
async def test_generate_retry_on_failure():
    """_call_ollama retries on failure — fails twice, succeeds third call."""
    config = {**DEFAULT_CONFIG, "max_retries": 3}
    router = LLMRouter(config)
    mock_resp = make_mock_response()

    call_count = 0

    async def flaky_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Connection refused")
        return mock_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = flaky_post
        mock_client_cls.return_value = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await router.generate("Test retry prompt", tier="quick")

    assert result == "Test LLM output"
    assert call_count == 3
