"""
飞书知识库 + 云文档采集器

从飞书 Wiki 知识库中拉取 docx 类型文档，
通过 blocks API 获取结构化内容，转为 Markdown 后交给 pipeline 处理。

用法：
    collector = FeishuCollector()
    for article in collector.collect(limit=50):
        ...

配置（环境变量）：
    FEISHU_APP_ID — 飞书自建应用 App ID
    FEISHU_APP_SECRET — App Secret
    FEISHU_WIKI_SPACE_IDS — 逗号分隔的 space ID，空 = 全部可访问
    FEISHU_API_BASE — API 基础 URL（默认 open.feishu.cn）
"""

import hashlib
from typing import Any, Iterator

import structlog

from .base import BaseCollector

logger = structlog.get_logger(__name__)


class FeishuCollector(BaseCollector):
    """飞书知识库采集器。"""

    def __init__(self, name: str = "feishu"):
        super().__init__(name)
        self._client = None

    def close(self) -> None:
        """Close the underlying FeishuClient HTTP session."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _get_client(self):
        """延迟初始化飞书 API 客户端（避免导入时就获取 token）。"""
        if self._client is None:
            from core.config import settings
            from .feishu_client import FeishuClient

            self._client = FeishuClient(
                app_id=settings.feishu_app_id,
                app_secret=settings.feishu_app_secret,
                api_base=settings.feishu_api_base,
            )
        return self._client

    def collect(self, **kwargs) -> Iterator[dict[str, Any]]:
        """采集飞书知识库文档。

        Kwargs:
            space_ids: list[str] — 指定知识库 ID，不传则用配置或自动发现
            limit: int — 最大文档数
            node_types: list[str] — 过滤 obj_type，默认 ["docx"]

        Yields:
            标准化的文章字典，兼容 chunker 和 indexer
        """
        from core.config import settings
        from .feishu_block_parser import blocks_to_text

        client = self._get_client()
        space_ids = kwargs.get("space_ids") or settings.feishu_space_id_list
        limit = kwargs.get("limit")
        node_types = kwargs.get("node_types") or ["docx"]

        yielded = 0

        # 如果没有指定 space_ids，自动发现所有可访问的 space
        if not space_ids:
            logger.info("feishu_discovering_spaces")
            try:
                spaces = client.list_spaces()
                space_ids = [s["space_id"] for s in spaces]
                logger.info("feishu_spaces_found", count=len(space_ids))
            except Exception as e:
                logger.error("feishu_list_spaces_failed", error=str(e))
                return

        for space_id in space_ids:
            if limit and yielded >= limit:
                break

            logger.info("feishu_processing_space", space_id=space_id)

            try:
                space_name = self._get_space_name(client, space_id)
            except Exception:
                space_name = space_id

            try:
                for node in client.list_nodes(space_id):
                    if limit and yielded >= limit:
                        break

                    obj_type = node.get("obj_type", "")

                    # 只处理指定的文档类型
                    if obj_type not in node_types:
                        if obj_type in ("doc",):
                            logger.warning(
                                "feishu_skipping_old_doc_format",
                                node_token=node.get("node_token"),
                                title=node.get("title"),
                                obj_type=obj_type,
                            )
                        continue

                    # 拉取并转换文档
                    try:
                        article = self._process_node(client, node, space_name, space_id)
                        if article:
                            yield article
                            yielded += 1
                    except Exception as e:
                        logger.error(
                            "feishu_node_process_failed",
                            node_token=node.get("node_token"),
                            title=node.get("title"),
                            error=str(e),
                        )
                        continue

            except Exception as e:
                logger.error("feishu_space_traversal_failed", space_id=space_id, error=str(e))
                continue

        logger.info("feishu_collection_completed", total_yielded=yielded)

    def _get_space_name(self, client, space_id: str) -> str:
        """获取 space 名称（从 list_spaces 缓存中查找）。"""
        for space in client.list_spaces():
            if space.get("space_id") == space_id:
                return space.get("name", space_id)
        return space_id

    def _process_node(
        self, client, node: dict, space_name: str, space_id: str
    ) -> dict[str, Any] | None:
        """处理单个 wiki node：获取 blocks → 转文本 → 构建 article dict。"""
        from .feishu_block_parser import blocks_to_text

        title = node.get("title", "")
        obj_token = node.get("obj_token", "")
        node_token = node.get("node_token", "")

        if not obj_token:
            logger.warning("feishu_node_no_obj_token", node_token=node_token)
            return None

        # 获取文档 blocks
        blocks = client.get_document_blocks(obj_token)
        if not blocks:
            logger.debug("feishu_empty_document", node_token=node_token, title=title)
            return None

        # 转为 Markdown 文本
        content = blocks_to_text(blocks)
        if not content.strip():
            logger.debug("feishu_empty_content", node_token=node_token, title=title)
            return None

        # 构建标准化 article dict
        content_hash = hashlib.sha256(f"{title}|{content}".encode()).hexdigest()
        url = f"https://feishu.cn/wiki/{node_token}"

        return {
            "title": title,
            "content": content,
            "source": f"Feishu:{space_name}",
            "language": "zh",
            "category": "wiki",
            "published_at": 0,
            "pub_time": "",
            "url": url,
            "lead": content[:200],
            "content_hash": content_hash,
            "feishu_space_id": space_id,
            "feishu_node_token": node_token,
            "feishu_obj_token": obj_token,
        }
