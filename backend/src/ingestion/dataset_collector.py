"""
HuggingFace 数据集采集器
使用 datasets 库加载公开数据集，如 ag_news 新闻分类数据集
"""
import structlog
from typing import Any, Iterator

from .base import BaseCollector

logger = structlog.get_logger()

# 支持的数据集配置
DATASET_CONFIGS: dict[str, dict[str, Any]] = {
    "ag_news": {
        "name": "ag_news",
        "description": "AG News 新闻分类数据集，包含 4 种类别：World, Sports, Business, Sci/Tech",
        "language": "en",
        "split": "train",
        "category_map": {
            0: "world",
            1: "sports",
            2: "business",
            3: "sci_tech",
        },
    },
    "bbc_news": {
        "name": "mmenon/bbc-news-text-classification",
        "description": "BBC News 分类数据集，包含 5 种类别",
        "language": "en",
        "split": "train",
        "category_map": {
            0: "tech",
            1: "business",
            2: "sport",
            3: "entertainment",
            4: "politics",
        },
    },
}


class DatasetCollector(BaseCollector):
    """
    HuggingFace 数据集采集器

    继承自 BaseCollector，使用 datasets 库加载公开数据集。
    支持加载本地缓存的数据集，无需网络请求（首次加载后）。
    """

    def __init__(
        self,
        dataset_name: str = "ag_news",
        name: str = "huggingface",
        limit: int | None = None,
        split: str | None = None,
    ):
        """
        初始化数据集采集器

        Args:
            dataset_name: 数据集名称，默认 "ag_news"
            name: 采集器名称，默认 "huggingface"
            limit: 限制加载的样本数，None 表示全部加载
            split: 数据集分割，默认使用数据集配置
        """
        super().__init__(name)
        self.dataset_name = dataset_name
        self.limit = limit
        self.config = DATASET_CONFIGS.get(dataset_name, DATASET_CONFIGS["ag_news"])
        self.split = split or self.config.get("split", "train")

    @staticmethod
    def _load_dataset(dataset_name: str, split: str = "train"):
        """
        加载 HuggingFace 数据集

        Args:
            dataset_name: 数据集名称
            split: 数据集分割，默认 "train"

        Returns:
            datasets.Dataset 对象
        """
        # 延迟导入，避免 datasets 库未安装时影响其他采集器
        from datasets import load_dataset

        logger.info("[DatasetCollector] 正在加载数据集", dataset=dataset_name, split=split)
        dataset = load_dataset(dataset_name, split=split)
        logger.info("[DatasetCollector] 数据集加载完成", dataset=dataset_name, size=len(dataset))
        return dataset

    def _map_category(self, label: int) -> str:
        """
        将数字标签映射为分类名称

        Args:
            label: 数字标签

        Returns:
            分类名称字符串
        """
        category_map = self.config.get("category_map", {})
        return category_map.get(label, f"unknown_{label}")

    def _parse_article(self, item: dict[str, Any], index: int) -> dict[str, Any] | None:
        """
        解析单条数据集记录

        Args:
            item: 数据集单条记录
            index: 记录索引

        Returns:
            标准化的文章字典，解析失败返回 None
        """
        try:
            # AG News 数据集格式: label, title, description
            # 不同数据集可能有不同格式，尝试多种字段
            label = item.get("label", item.get("labels", 0))
            title = item.get("title", item.get("headline", ""))
            content = item.get("description", item.get("content", item.get("text", "")))

            # 如果 content 仍然为空，尝试拼接多个字段
            if not content:
                # 尝试从其他字段构建内容
                parts = []
                for key in ["summary", "content", "article", "body"]:
                    if key in item and item[key]:
                        parts.append(item[key])
                content = " | ".join(parts)

            if not title and not content:
                logger.debug("[DatasetCollector] 记录缺少标题和内容", index=index)
                return None

            # 获取分类
            category = self._map_category(label) if isinstance(label, int) else str(label)

            # 解析发布时间（数据集通常没有时间戳，使用当前时间或索引作为伪时间）
            # 使用索引的逆序模拟发布时间（数据集中较早的数据索引较小）
            published_at = 0

            return {
                "title": title.strip() if title else "",
                "content": content.strip() if content else title.strip() if title else "",
                "source": f"HuggingFace:{self.dataset_name}",
                "language": self.config.get("language", "en"),
                "category": category,
                "published_at": published_at,
                "dataset_index": index,
            }

        except Exception as e:
            logger.warning("[DatasetCollector] 解析记录失败", index=index, error=str(e))
            return None

    def collect(self, **kwargs) -> Iterator[dict[str, Any]]:
        """
        采集数据集中的所有记录

        Yields:
            标准化的文章字典
        """
        limit = kwargs.get("limit") or self.limit
        logger.info("[DatasetCollector] 开始采集数据集", dataset=self.dataset_name, limit=limit)

        try:
            dataset = self._load_dataset(self.config["name"], split=self.split)

            # 应用 limit 限制
            records = dataset
            if limit is not None:
                records = dataset.select(range(min(limit, len(dataset))))
                logger.info("[DatasetCollector] 已应用样本数限制", limit=limit, actual=len(records))

            success_count = 0
            for idx, item in enumerate(records):
                article = self._parse_article(item, idx)
                if article:
                    yield article
                    success_count += 1

            logger.info("[DatasetCollector] 数据集采集完成", dataset=self.dataset_name, success=success_count)

        except Exception as e:
            logger.error("[DatasetCollector] 数据集加载失败", dataset=self.dataset_name, error=str(e))
            raise

