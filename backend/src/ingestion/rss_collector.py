"""
RSS 采集器 - 支持中英文新闻源
使用 feedparser 解析 RSS/Atom 订阅源，使用 trafilatura 抓取全文
"""
import hashlib
from datetime import datetime, timezone
from typing import Any, Iterator

import feedparser
import structlog

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
    {"name": "Reuters World", "url": "https://www.reutersagency.com/feed/?taxonomy=best-topics&post_type=best", "language": "en", "category": "finance"},
    # 中文科技/创业新闻源
    {"name": "36氪", "url": "https://36kr.com/feed", "language": "zh", "category": "tech"},
    {"name": "少数派", "url": "https://sspai.com/feed", "language": "zh", "category": "tech"},
    {"name": "钛媒体", "url": "https://www.tmtpost.com/feed", "language": "zh", "category": "tech"},
    {"name": "爱范儿", "url": "https://www.ifanr.com/feed", "language": "zh", "category": "tech"},
    # 中文综合新闻源
    {"name": "澎湃新闻", "url": "https://www.thepaper.cn/rss", "language": "zh", "category": "news"},
    {"name": "参考消息", "url": "http://www.cankaoxiaoxi.com/rss/", "language": "zh", "category": "news"},
    # 英文金融源
    {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "language": "en", "category": "finance"},
    {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/markets/news.rss", "language": "en", "category": "finance"},
    {"name": "FT", "url": "https://www.ft.com/rss/home", "language": "en", "category": "finance"},
    {"name": "WSJ", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "language": "en", "category": "finance"},
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex", "language": "en", "category": "finance"},
    # 中文金融源
    {"name": "华尔街见闻", "url": "https://wallstreetcn.com/rss", "language": "zh", "category": "finance"},
    {"name": "财新", "url": "https://rsshub.app/caixin/latest", "language": "zh", "category": "finance"},
    {"name": "第一财经", "url": "https://rsshub.app/yicai/brief", "language": "zh", "category": "finance"},
]


def _compute_content_hash(title: str, content: str) -> str:
    """计算内容 hash 用于去重"""
    return hashlib.sha256(f"{title}|{content}".encode()).hexdigest()


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
    def _fetch_feed_with_retry(url: str) -> feedparser.FeedParserDict:
        """获取并解析 RSS 源（带重试和多次尝试）"""
        logger.debug("[RSSCollector] 正在获取订阅源", url=url)
        last_exc = None
        for attempt in range(3):
            try:
                feed = feedparser.parse(url)
                if feed.entries or not feed.bozo:
                    return feed
                logger.warning("[RSSCollector] bozo retry", url=url, attempt=attempt + 1)
            except Exception as e:
                last_exc = e
                logger.warning("[RSSCollector] fetch exception", url=url, attempt=attempt + 1, error=str(e))
        # Fallback: return feed even with bozo (some valid feeds have bozo bit)
        if 'feed' in dir() and feed.entries:
            return feed
        raise RuntimeError(f"无法解析 RSS 源: {url}") from last_exc

    @staticmethod
    def _fetch_full_text(url: str) -> str | None:
        """
        使用 trafilatura 抓取页面全文

        Args:
            url: 文章 URL

        Returns:
            全文内容，抓取失败返回 None
        """
        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                # 提取正文，禁用 XML 输出以获得更自然的文本
                text = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=True,
                    output_format="txt",
                )
                return text if text else None
            return None
        except Exception as e:
            logger.debug("trafilatura_fetch_failed", url=url, error=str(e))
            return None

    def _parse_entry(
        self,
        entry: Any,
        source_name: str,
        language: str,
        category: str,
        fetch_full_text: bool = False,
    ) -> dict[str, Any] | None:
        """
        解析单条 RSS 条目

        Args:
            entry: feedparser 条目对象
            source_name: 来源名称
            language: 语言代码
            category: 分类
            fetch_full_text: 是否使用 trafilatura 抓取全文

        Returns:
            标准化的文章字典，解析失败返回 None
        """
        try:
            # 获取标题
            title = getattr(entry, "title", None) or ""
            title = title.strip()

            # 获取内容摘要
            content = ""
            if hasattr(entry, "summary"):
                content = entry.summary
            elif hasattr(entry, "content"):
                if entry.content and len(entry.content) > 0:
                    content = entry.content[0].value
            content = content.strip()

            # 如果没有摘要，从 title 生成
            if not content and title:
                content = title

            # 获取发布时间
            published_at = 0
            pub_time_str = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                published_at = int(dt.timestamp())
                pub_time_str = dt.isoformat()
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                published_at = int(dt.timestamp())
                pub_time_str = dt.isoformat()

            # 获取链接
            link = getattr(entry, "link", "") or ""

            # 尝试抓取全文
            full_text = None
            if fetch_full_text and link:
                full_text = self._fetch_full_text(link)

            # 如果 trafilatura 抓不到，用 RSS snippet 作为全文
            if full_text is None:
                full_text = content

            # 计算 content_hash
            content_hash = _compute_content_hash(title, full_text)

            # 尝试提取导语（lead）- 取摘要的前 200 字作为导语
            lead = content[:200] if len(content) > 200 else content

            return {
                "title": title,
                "content": full_text,  # 完整正文
                "lead": lead,  # 导语
                "source": source_name,
                "language": language,
                "category": category,
                "published_at": published_at,
                "pub_time": pub_time_str,
                "url": link,
                "content_hash": content_hash,
            }
        except Exception as e:
            logger.warning("[RSSCollector] 解析条目失败", error=str(e), entry_title=getattr(entry, "title", ""))
            return None

    def collect(self, fetch_full_text: bool = False, **kwargs) -> Iterator[dict[str, Any]]:
        """
        采集所有配置的 RSS 源

        Args:
            fetch_full_text: 是否使用 trafilatura 抓取全文（默认 False，节省时间）

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
                entry_count = 0
                for article in self.collect_from_source(
                    url=url,
                    source_name=source_name,
                    language=language,
                    category=category,
                    fetch_full_text=fetch_full_text,
                    limit=kwargs.get("limit"),
                ):
                    yield article
                    entry_count += 1

                logger.info("[RSSCollector] 订阅源采集完成", source=source_name, count=entry_count)

            except Exception as e:
                logger.error("[RSSCollector] 订阅源采集失败", source=source_name, error=str(e))
                continue

    def collect_from_source(
        self,
        url: str,
        source_name: str,
        language: str = "en",
        category: str = "news",
        fetch_full_text: bool = False,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        从指定 RSS 源采集（临时单源）

        Args:
            url: RSS 源 URL
            source_name: 来源名称
            language: 语言代码
            category: 分类
            fetch_full_text: 是否抓取全文

        Yields:
            标准化的文章字典
        """
        logger.info("[RSSCollector] 采集指定订阅源", source=source_name, url=url)

        try:
            feed = self._fetch_feed_with_retry(url)

            for index, entry in enumerate(feed.entries or []):
                if limit is not None and index >= limit:
                    break
                article = self._parse_entry(entry, source_name, language, category, fetch_full_text)
                if article:
                    yield article

        except Exception as e:
            logger.error("[RSSCollector] 指定订阅源采集失败", source=source_name, error=str(e))
