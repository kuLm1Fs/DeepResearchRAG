"""
Hacker News API 采集器
使用 httpx 调用 HN Firebase API，无需认证即可获取最新文章
"""
import httpx
import structlog
from datetime import datetime, timezone
from typing import Any, Iterator
import hashlib

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .base import BaseCollector

logger = structlog.get_logger()

# HN Firebase API 基础 URL
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
# 默认采集最新文章数量
DEFAULT_LIMIT = 100


class HNCollector(BaseCollector):
    """
    Hacker News 文章采集器

    继承自 BaseCollector，使用 httpx 调用 HN Firebase API。
    获取最新文章、热门文章或指定ID的文章，带 tenacity 重试机制。
    """

    def __init__(
        self,
        name: str = "hackernews",
        limit: int | None = None,
        max_stories: int | None = None,
    ):
        """
        初始化 HN 采集器

        Args:
            name: 采集器名称，默认 "hackernews"
            limit: 每次采集的最大文章数，默认 100
            max_stories: limit 的兼容别名
        """
        super().__init__(name)
        self.limit = max_stories if max_stories is not None else (limit or DEFAULT_LIMIT)
        self.max_stories = self.limit

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _fetch_json(url: str) -> dict[str, Any] | list[int] | int | str | None:
        """
        获取 JSON 数据（带重试）

        Args:
            url: API 端点 URL

        Returns:
            解析后的 JSON 数据

        Raises:
            httpx.HTTPError: 网络请求失败时重试
        """
        logger.debug("[HNCollector] 正在请求 HN API", url=url)
        with httpx.Client(timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()

    def _get_top_stories(self) -> list[int]:
        """
        获取热门文章 ID 列表

        Returns:
            文章 ID 列表
        """
        url = f"{HN_API_BASE}/topstories.json"
        story_ids = self._fetch_json(url)
        if not isinstance(story_ids, list):
            logger.error("[HNCollector] 获取热门故事ID失败", type=type(story_ids))
            return []
        return story_ids[: self.limit]

    def _get_new_stories(self) -> list[int]:
        """
        获取最新文章 ID 列表

        Returns:
            文章 ID 列表
        """
        url = f"{HN_API_BASE}/newstories.json"
        story_ids = self._fetch_json(url)
        if not isinstance(story_ids, list):
            logger.error("[HNCollector] 获取最新故事ID失败", type=type(story_ids))
            return []
        return story_ids[: self.limit]

    def _get_best_stories(self) -> list[int]:
        """
        获取最佳文章 ID 列表

        Returns:
            文章 ID 列表
        """
        url = f"{HN_API_BASE}/beststories.json"
        story_ids = self._fetch_json(url)
        if not isinstance(story_ids, list):
            logger.error("[HNCollector] 获取最佳故事ID失败", type=type(story_ids))
            return []
        return story_ids[: self.limit]

    def _fetch_article(self, item_id: int) -> dict[str, Any] | None:
        """
        获取单篇文章详情

        Args:
            item_id: 文章 ID

        Returns:
            标准化后的文章字典，失败返回 None
        """
        url = f"{HN_API_BASE}/item/{item_id}.json"
        try:
            item = self._fetch_json(url)
            if not isinstance(item, dict):
                return None

            # HN API 返回的文章类型包括: story, job, poll, comment, etc.
            # 我们只处理 story 和 job 类型
            item_type = item.get("type", "")
            if item_type not in ("story", "job"):
                return None

            # 解析标题
            title = item.get("title", "")
            if not title:
                return None

            # 解析 URL
            url_link = item.get("url", "") or f"https://news.ycombinator.com/item?id={item_id}"

            # 解析内容（优先 HN text，必要时用 trafilatura 抓取外链全文）
            content = item.get("text", "") or ""
            full_text = content or self._fetch_full_text(url_link) or url_link

            # 解析发布时间（Unix timestamp）
            timestamp = item.get("time", 0)
            published_at = int(timestamp) if timestamp else 0

            # 解析分数
            score = item.get("score", 0)

            # 解析作者
            author = item.get("by", "anonymous")

            # 解析评论数
            descendants = item.get("descendants", 0)

            # 组合内容（包含元数据）
            full_content = full_text
            if not full_content:
                full_content = f"HN Score: {score} | Comments: {descendants} | Author: {author}"
            else:
                full_content = f"{full_text}\n\nHN Score: {score} | Comments: {descendants} | Author: {author}"

            content_hash = hashlib.sha256(f"{title}|{full_content}".encode()).hexdigest()

            return {
                "title": title,
                "content": full_content.strip(),
                "source": "HackerNews",
                "language": "en",  # HN 主要是英文
                "category": "tech",
                "published_at": published_at,
                "url": url_link,
                "content_hash": content_hash,
                "pub_time": datetime.fromtimestamp(published_at, tz=timezone.utc).isoformat() if published_at else "",
                "hn_score": score,
                "hn_comments": descendants,
                "hn_author": author,
            }

        except Exception as e:
            logger.warning("[HNCollector] 获取文章详情失败", item_id=item_id, error=str(e))
            return None

    @staticmethod
    def _fetch_full_text(url: str) -> str | None:
        """Fetch external story text with trafilatura when available."""
        if "news.ycombinator.com/item" in url:
            return None
        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None
            return trafilatura.extract(
                downloaded,
                include_comments=False,
                include_tables=True,
                output_format="txt",
            )
        except Exception as exc:
            logger.debug("hn_trafilatura_fetch_failed", url=url, error=str(exc))
            return None

    def collect(self, story_type: str = "top", **kwargs) -> Iterator[dict[str, Any]]:
        """
        采集 Hacker News 文章

        Args:
            story_type: 故事类型，可选 "top"(热门), "new"(最新), "best"(最佳)

        Yields:
            标准化的文章字典
        """
        limit = kwargs.get("limit") or self.limit
        logger.info("[HNCollector] 开始采集 HN 文章", story_type=story_type, limit=limit)

        # 根据类型获取文章 ID 列表
        if story_type == "new":
            story_ids = self._get_new_stories()[:limit]
        elif story_type == "best":
            story_ids = self._get_best_stories()[:limit]
        else:
            story_ids = self._get_top_stories()[:limit]

        if not story_ids:
            logger.warning("[HNCollector] 未获取到文章ID列表")
            return

        logger.info("[HNCollector] 获取到文章ID数量", count=len(story_ids))

        # 逐个获取文章详情
        success_count = 0
        for item_id in story_ids:
            article = self._fetch_article(item_id)
            if article:
                yield article
                success_count += 1

        logger.info("[HNCollector] HN 文章采集完成", success=success_count, total=len(story_ids))

    def collect_by_ids(self, item_ids: list[int]) -> Iterator[dict[str, Any]]:
        """
        根据指定 ID 列表采集文章

        Args:
            item_ids: 文章 ID 列表

        Yields:
            标准化的文章字典
        """
        logger.info("[HNCollector] 开始采集指定ID文章", count=len(item_ids))

        success_count = 0
        for item_id in item_ids:
            article = self._fetch_article(item_id)
            if article:
                yield article
                success_count += 1

        logger.info("[HNCollector] 指定ID文章采集完成", success=success_count, total=len(item_ids))
