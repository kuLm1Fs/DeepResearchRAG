# Ingestion module - 数据采集模块
from .base import BaseCollector
from .dataset_collector import DATASET_CONFIGS, DatasetCollector
from .feishu_collector import FeishuCollector
from .hn_collector import HNCollector
from .indexer import index_articles
from .pipeline import IngestionPipeline, Pipeline
from .rss_collector import RSS_SOURCES, RSSCollector

__all__ = [
    "BaseCollector",
    "RSSCollector",
    "RSS_SOURCES",
    "HNCollector",
    "DatasetCollector",
    "DATASET_CONFIGS",
    "FeishuCollector",
    "Pipeline",
    "IngestionPipeline",
    "index_articles",
]
