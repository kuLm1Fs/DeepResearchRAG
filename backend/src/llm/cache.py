"""LLM 响应缓存模块。

基于文件的 LLM 响应缓存，避免重复调用 API。
缓存 key 包含模型版本和 prompt 版本，换模型/换 prompt 时旧缓存自动失效。
"""
import hashlib
import json
from pathlib import Path
from typing import Any

from core import get_logger

logger = get_logger(__name__)


class CachedLLM:
    """带缓存的 LLM 客户端包装器。

    将 LLM 响应缓存到本地 JSON 文件，相同输入直接返回缓存结果。
    """

    def __init__(self, llm: Any, cache_dir: str | Path):
        """
        Args:
            llm: 底层 LLM 客户端（需有 chat 方法）。
            cache_dir: 缓存文件存储目录。
        """
        self.llm = llm
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _make_key(self, messages: list[dict]) -> str:
        """根据消息内容生成缓存 key。"""
        content = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_cache_path(self, key: str) -> Path:
        """获取缓存文件路径。"""
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> str | None:
        """读取缓存。"""
        path = self._get_cache_path(key)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                logger.debug("cache_hit", key=key[:16])
                return data.get("response")
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def _write_cache(self, key: str, response: str) -> None:
        """写入缓存。"""
        path = self._get_cache_path(key)
        path.write_text(json.dumps({"response": response}, ensure_ascii=False))
        logger.debug("cache_set", key=key[:16])

    async def chat(self, messages: list[dict], **kwargs) -> str:
        """带缓存的 chat 调用。"""
        key = self._make_key(messages)
        cached = self._read_cache(key)
        if cached is not None:
            return cached

        response = await self.llm.chat(messages, **kwargs)
        self._write_cache(key, response)
        return response

    async def stream_chat(self, messages: list[dict], **kwargs):
        """流式 chat 不使用缓存，直接透传。"""
        async for chunk in self.llm.stream_chat(messages, **kwargs):
            yield chunk
