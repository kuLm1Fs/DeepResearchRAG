from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Protocol

import tenacity

from core import get_logger

logger = get_logger(__name__)

# Retryable status codes from LLM APIs
_RETRYABLE_STATUSES = {429, 500, 502, 503}


def _is_retryable(exc: BaseException) -> bool:
    """Check if an exception is retryable (rate limit or server error)."""
    from openai import APIStatusError, APITimeoutError, APIConnectionError

    if isinstance(exc, APITimeoutError | APIConnectionError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code in _RETRYABLE_STATUSES:
        return True
    return False


def _make_retry():
    """Create a tenacity retry decorator for LLM calls."""
    return tenacity.retry(
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_exponential(multiplier=1, min=1, max=10),
        retry=tenacity.retry_if_exception(_is_retryable),
        before_sleep=lambda retry_state: logger.warning(
            "llm_retry",
            attempt=retry_state.attempt_number,
            error=str(retry_state.outcome.exception()) if retry_state.outcome else "",
        ),
        reraise=True,
    )


_retry = _make_retry()


class Message(Protocol):
    role: str
    content: str


class BaseLLM(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, api_key: str, model: str, **kwargs):
        self.api_key = api_key
        self.model = model
        self._client = None

    @abstractmethod
    async def chat(self, messages: list[Message], **kwargs) -> str:
        """Send a chat request and return the response text."""
        pass

    @abstractmethod
    async def stream_chat(self, messages: list[Message], **kwargs) -> AsyncIterator[str]:
        """Send a chat request and yield response tokens."""
        pass

    def _format_messages(self, messages: list[Message | dict[str, Any]]) -> list[dict]:
        formatted = []
        for message in messages:
            if isinstance(message, dict):
                formatted.append({
                    "role": message["role"],
                    "content": message["content"],
                })
            else:
                formatted.append({
                    "role": message.role,
                    "content": message.content,
                })
        return formatted

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.close()
            self._client = None


# Provider-specific base URLs
_PROVIDER_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    # "openai" uses the SDK default (https://api.openai.com/v1)
}

_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4o-mini",
    "qwen": "qwen-max",
}


class OpenAICompatibleLLM(BaseLLM):
    """Single LLM class for all OpenAI-API-compatible providers (DeepSeek, OpenAI, Qwen, etc.)."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None, **kwargs):
        super().__init__(api_key, model, **kwargs)
        self._base_url = base_url

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            kwargs: dict[str, Any] = {
                "api_key": self.api_key,
                "timeout": 60.0,
            }
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    @_retry
    async def chat(self, messages: list[Message], **kwargs) -> str:
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.model,
            messages=self._format_messages(messages),
            **kwargs
        )
        return response.choices[0].message.content or ""

    async def stream_chat(self, messages: list[Message], **kwargs) -> AsyncIterator[str]:
        client = self._get_client()
        stream = await client.chat.completions.create(
            model=self.model,
            messages=self._format_messages(messages),
            stream=True,
            **kwargs
        )
        try:
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            await stream.close()


# Backward-compatible aliases
DeepSeekLLM = OpenAICompatibleLLM
OpenAILLM = OpenAICompatibleLLM
QwenLLM = OpenAICompatibleLLM


def create_llm(provider: str, api_key: str, model: str) -> BaseLLM:
    """Factory function to create LLM instance by provider name."""
    if provider not in _PROVIDER_DEFAULT_MODELS:
        raise ValueError(f"Unknown LLM provider: {provider}. Available: {list(_PROVIDER_DEFAULT_MODELS.keys())}")
    return OpenAICompatibleLLM(
        api_key=api_key,
        model=model or _PROVIDER_DEFAULT_MODELS[provider],
        base_url=_PROVIDER_BASE_URLS.get(provider),
    )
