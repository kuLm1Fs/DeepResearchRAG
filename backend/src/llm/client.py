from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Protocol

from core import get_logger

logger = get_logger(__name__)


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


class DeepSeekLLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "deepseek-chat", **kwargs):
        super().__init__(api_key, model, **kwargs)
        self._base_url = "https://api.deepseek.com"

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self._base_url,
            )
        return self._client

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
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class OpenAILLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", **kwargs):
        super().__init__(api_key, model, **kwargs)

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

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
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class QwenLLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "qwen-max", **kwargs):
        super().__init__(api_key, model, **kwargs)
        self._base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self._base_url,
            )
        return self._client

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
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


def create_llm(provider: str, api_key: str, model: str) -> BaseLLM:
    """Factory function to create LLM instance by provider name."""
    providers = {
        "deepseek": DeepSeekLLM,
        "openai": OpenAILLM,
        "qwen": QwenLLM,
    }
    if provider not in providers:
        raise ValueError(f"Unknown LLM provider: {provider}. Available: {list(providers.keys())}")
    return providers[provider](api_key=api_key, model=model)
