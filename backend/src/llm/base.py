"""LLM Base classes"""
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class LLMResponse:
    """LLM response container"""
    def __init__(self, content: str, usage: dict[str, Any], model: str):
        self.content = content
        self.usage = usage
        self.model = model


class BaseLLM(ABC):
    """Abstract base class for LLM providers"""

    def __init__(self, api_key: str = "", model: str = "", **kwargs):
        self.api_key = api_key
        self.model = model

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs
    ) -> LLMResponse:
        """Send a chat request and return the response."""
        pass

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs
    ) -> AsyncIterator[str]:
        """Send a chat request and yield response tokens."""
        pass