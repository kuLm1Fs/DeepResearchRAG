"""
RSS 采集器 - 支持中英文新闻源
使用 feedparser 解析 RSS/Atom 订阅源，支持 tenacity 重试机制
"""
import feedparser
import structlog
from datetime import datetime, timezone
from typing import Any, Iterator

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .base import BaseCollector

logger = structlog.get_logger()

# 预定义 RSS 源配置：支持 TechCrunch, The Verge, BBC, 36kr, 少数派等中英文源
RSS_SOURCES: list[dict[str, str]] = [
    # 英文科技新闻源
    {"name": "TechCrunch", "url": "https://techcrunch.com/feed/", "language": "en", "category": "tech"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "language": "en", "category": "tech"},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "language": "en", "category": "tech"},
    # 英文综合新闻源
    {"name": "BBC World", "url": "http://feeds.bbci.co.uk/news/world/rss.xml", "language": "en", "category": "news"},
    {"name": "Reuters World", "url": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best", "language": "en", "category": "news"},
    # 中文科技/创业新闻源
    {"name": "36氪", "url": "https://36kr.com/feed", "language": "zh", "category": "tech"},
    {"name": "少数派", "url": "https://sspai.com/feed", "language": "zh", "category": "tech"},
    {"name": "钛媒体", "url": "https://www.tmtpost.com/feed", "language": "zh", "category": "tech"},
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed", "language": "zh", "category": "tech"},
    # 中文综合新闻源
    {"name": "澎湃新闻", "url": "https://www.thepaper.cn/rss", "language": "zh", "category": "news"},
    {"name": "参考消息", "url": "http://www.cankaoxiaoxi.com/rss/", "language": "zh", "category": "news"},
]


class RSSCollector(BaseCollector):
    """
    RSS 订阅源采集器

    继承自 BaseCollector，使用 feedparser 解析 RSS/Atom 格式。
    支持中英文新闻源采集，自动检测语言，带 tenacity 重试机制。
    """

    def __init__(self, name: str = "rss", sources: list[dict[str, str]] | None = None):
        """
        初始化 RSS 采集器

        Args:
            name: 采集器名称，默认 "rss"
            sources: RSS 源配置列表，默认使用预定义配置
        """
        super().__init__(name)
        self.sources = sources or RSS_SOURCES

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),  # 最多重试3次
        wait=wait_exponential(multiplier=1, min=2, max=10),  # 指数退避 2-10 秒
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def _fetch_feed(url: str) -> feedparser.FeedParserDict:
        """
        获取并解析 RSS 源（带重试）

        Args:
            url: RSS 源 URL

        Returns:
            解析后的 feed 对象

        Raises:
            RuntimeError: 解析失败时重试
        """
        logger.debug("[RSSCollector] 正在获取订阅源", url=url)
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            # 只有在无法获取任何条目时才视为错误
            raise RuntimeError(f"无法解析 RSS 源: {url}")
        return feed

    def _parse_entry(self, entry: Any, source_name: str, language: str, category: str) -> dict[str, Any] | None:
        """
        解析单条 RSS 条目

        Args:
            entry: feedparser 条目对象
            source_name: 来源名称
            language: 语言代码
            category: 分类

        Returns:
            标准化的文章字典，解析失败返回 None
        """
        try:
            # 获取标题
            title = getattr(entry, "title", None) or ""
            title = title.strip()

            # 获取内容摘要，优先使用 summary，其次 content
            content = ""
            if hasattr(entry, "summary"):
                content = entry.summary
            elif hasattr(entry, "content"):
                # content 是列表，取第一个元素
                if entry.content and len(entry.content) > 0:
                    content = entry.content[0].value
            content = content.strip()

            # 如果没有摘要，尝试从 title 生成（用于纯标题场景）
            if not content and title:
                content = title

            # 获取发布时间
            published_at = 0
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                published_at = int(dt.timestamp())
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                published_at = int(dt.timestamp())

            # 获取链接
            link = getattr(entry, "link", "") or ""

            return {
                "title": title,
                "content": content,
                "source": source_name,
                "language": language,
                "category": category,
                "published_at": published_at,
                "url": link,
            }
        except Exception as e:
            logger.warning("[RSSCollector] 解析条目失败", error=str(e), entry_title=getattr(entry, "title", ""))
            return None

    def collect(self, **kwargs) -> Iterator[dict[str, Any]]:
        """
        采集所有配置的 RSS 源

        Yields:
            标准化的文章字典
        """
        for source in self.sources:
            url = source["url"]
            source_name = source.get("name", url)
            language = source.get("language", "en")
            category = source.get("category", "news")

            logger.info("[RSSCollector] 开始采集订阅源", source=source_name, url=url)

            try:
                feed = self._fetch_feed(url)

                entry_count = 0
                for entry in feed.entries or []:
                    article = self._parse_entry(entry, source_name, language, category)
                    if article:
                        yield article
                        entry_count += 1

                logger.info("[RSSCollector] 订阅源采集完成", source=source_name, count=entry_count)

            except Exception as e:
                logger.error("[RSSCollector] 订阅源采集失败", source=source_name, error=str(e))
                continue

    def collect_from_source(self, url: str, source_name: str, language: str = "en", category: str = "news") -> Iterator[dict[str, Any]]:
        """
        从指定 RSS 源采集（临时单源）

        Args:
            url: RSS 源 URL
            source_name: 来源名称
            language: 语言代码
            category: 分类

        Yields:
            标准化的文章字典
        """
        logger.info("[RSSCollector] 采集指定订阅源", source=source_name, url=url)

        try:
            feed = self._fetch_feed(url)

            for entry in feed.entries or []:
                article = self._parse_entry(entry, source_name, language, category)
                if article:
                    yield article

        except Exception as e:
            logger.error("[RSSCollector] 指定订阅源采集失败", source=source_name, error=str(e))
