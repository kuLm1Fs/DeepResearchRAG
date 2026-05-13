"""Qwen LLM 客户端（备选）"""
import os
from typing import AsyncIterator, Optional
import httpx

from .base import BaseLLM, LLMResponse

class QwenClient(BaseLLM):
    """Qwen 通义千问客户端"""

    def __init__(
        self,
        model: str = "qwen-turbo",
        api_key: Optional[str] = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        **kwargs
    ):
        self.model = model
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.base_url = base_url
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            },
            timeout=60.0
        )

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs
        }
        response = await self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload
        )
        response.raise_for_status()
        data = response.json()
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            usage=data.get("usage", {}),
            model=data.get("model", self.model)
        )

    async def stream_chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs
    ) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs
        }
        async with self._client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    if line.strip() == "data: [DONE]":
                        break
                    import json
                    data = json.loads(line[6:])
                    if content := data["choices"][0]["delta"].get("content"):
                        yield content

    async def close(self):
        await self._client.aclose()