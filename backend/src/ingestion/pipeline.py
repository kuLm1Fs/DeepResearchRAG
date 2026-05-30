"""
采集调度器 - 管理多个采集器，支持单独触发或批量触发
"""
import asyncio
import structlog
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Iterator

from .base import BaseCollector

logger = structlog.get_logger()


class Pipeline:
    """
    采集调度器

    管理多个采集器的生命周期，支持：
    - 注册多个采集器
    - 单独触发某个采集器
    - 批量触发所有采集器
    - 并行/串行执行模式
    - 采集结果回调处理
    """

    def __init__(self, name: str = "ingestion_pipeline", max_workers: int = 4):
        """
        初始化采集调度器

        Args:
            name: 调度器名称
            max_workers: 最大并行工作线程数
        """
        self.name = name
        self.max_workers = max_workers
        self.collectors: dict[str, BaseCollector] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def register(self, collector: BaseCollector) -> None:
        """
        注册采集器

        Args:
            collector: 采集器实例
        """
        self.collectors[collector.name] = collector
        logger.info("[Pipeline] 注册采集器", name=collector.name, total=len(self.collectors))

    def register_defaults(self) -> None:
        """
        注册默认采集器。

        延迟导入具体采集器，避免导入 pipeline 时强制加载所有可选依赖。
        """
        from .dataset_collector import DatasetCollector
        from .hn_collector import HNCollector
        from .rss_collector import RSSCollector

        self.register(RSSCollector())
        self.register(HNCollector())
        self.register(DatasetCollector())

    def unregister(self, name: str) -> bool:
        """
        注销采集器

        Args:
            name: 采集器名称

        Returns:
            是否成功注销
        """
        if name in self.collectors:
            del self.collectors[name]
            logger.info("[Pipeline] 注销采集器", name=name, remaining=len(self.collectors))
            return True
        return False

    def get_collector(self, name: str) -> BaseCollector | None:
        """
        获取指定采集器

        Args:
            name: 采集器名称

        Returns:
            采集器实例，不存在返回 None
        """
        return self.collectors.get(name)

    def list_collectors(self) -> list[str]:
        """
        列出所有已注册的采集器名称

        Returns:
            采集器名称列表
        """
        return list(self.collectors.keys())

    def collect_one(self, name: str, **kwargs) -> Iterator[dict[str, Any]]:
        """
        触发单个采集器

        Args:
            name: 采集器名称
            **kwargs: 传递给采集器的参数

        Yields:
            标准化的文章字典
        """
        collector = self.collectors.get(name)
        if not collector:
            logger.error("[Pipeline] 采集器不存在", name=name)
            return

        logger.info("[Pipeline] 触发单个采集器", collector=name)
        try:
            yield from collector.collect(**kwargs)
        except Exception as e:
            logger.error("[Pipeline] 采集器执行失败", collector=name, error=str(e))

    def collect_all(self, parallel: bool = True, **kwargs) -> Iterator[dict[str, Any]]:
        """
        触发所有已注册的采集器

        Args:
            parallel: 是否并行执行，默认 True
            **kwargs: 传递给每个采集器的参数

        Yields:
            标准化的文章字典
        """
        logger.info("[Pipeline] 触发所有采集器", parallel=parallel, total=len(self.collectors))

        if not parallel:
            # 串行执行
            for name, collector in self.collectors.items():
                logger.debug("[Pipeline] 串行执行采集器", collector=name)
                try:
                    yield from collector.collect(**kwargs)
                except Exception as e:
                    logger.error("[Pipeline] 采集器执行失败", collector=name, error=str(e))
        else:
            # 并行执行 - 使用线程池
            futures = {}
            for name, collector in self.collectors.items():
                future = self._executor.submit(self._run_collector, collector, **kwargs)
                futures[future] = name
                logger.debug("[Pipeline] 提交采集器到线程池", collector=name)

            # 收集结果
            for future in futures:
                name = futures[future]
                try:
                    result = future.result()
                    if result:
                        for article in result:
                            yield article
                except Exception as e:
                    logger.error("[Pipeline] 并行采集器执行失败", collector=name, error=str(e))

    def _run_collector(self, collector: BaseCollector, **kwargs) -> Iterator[dict[str, Any]]:
        """
        在线城池中运行采集器

        Args:
            collector: 采集器实例
            **kwargs: 传递给采集器的参数

        Returns:
            采集结果迭代器
        """
        try:
            return list(collector.collect(**kwargs))
        except Exception as e:
            logger.error("[Pipeline] 采集器运行异常", collector=collector.name, error=str(e))
            return []

    async def collect_all_async(self, **kwargs) -> Iterator[dict[str, Any]]:
        """
        异步触发所有已注册的采集器（使用 asyncio）

        Args:
            **kwargs: 传递给每个采集器的参数

        Yields:
            标准化的文章字典
        """
        logger.info("[Pipeline] 异步触发所有采集器", total=len(self.collectors))

        # 使用 asyncio 运行采集器
        loop = asyncio.get_event_loop()

        async def run_collector_async(collector: BaseCollector) -> list[dict[str, Any]]:
            """在线程池中运行采集器并返回结果"""
            return await loop.run_in_executor(self._executor, lambda: list(collector.collect(**kwargs)))

        # 并行运行所有采集器
        tasks = [run_collector_async(c) for c in self.collectors.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("[Pipeline] 异步采集器执行失败", error=str(result))
                continue
            for article in result:
                yield article

    def shutdown(self) -> None:
        """
        关闭调度器，释放线程池资源
        """
        logger.info("[Pipeline] 关闭调度器", name=self.name)
        self._executor.shutdown(wait=True)

    def __enter__(self) -> "Pipeline":
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """上下文管理器出口"""
        self.shutdown()


IngestionPipeline = Pipeline
