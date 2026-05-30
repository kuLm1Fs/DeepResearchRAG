# Ingestion module - 数据采集模块
from .base import BaseCollector
from .rss_collector import RSSCollector, RSS_SOURCES
from .hn_collector import HNCollector
from .dataset_collector import DatasetCollector, DATASET_CONFIGS
from .pipeline import IngestionPipeline, Pipeline
from .indexer import index_articles

__all__ = [
    "BaseCollector",
    "RSSCollector",
    "RSS_SOURCES",
    "HNCollector",
    "DatasetCollector",
    "DATASET_CONFIGS",
    "Pipeline",
    "IngestionPipeline",
    "index_articles",
]
