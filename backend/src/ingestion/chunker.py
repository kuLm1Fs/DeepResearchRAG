"""
文章切分器 - 将文章按固定头部 + 正文片段切分为多个 chunk
"""
import hashlib
import re
from typing import Any

import structlog

from core import get_logger

logger = get_logger(__name__)

# 默认 max_tokens=512，估算 1 token ≈ 2 chars，所以 max_chars = 1024
DEFAULT_MAX_CHARS = 512 * 2


def make_content_hash(content: str) -> str:
    """计算内容 SHA256 哈希"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def chunk_article(article: dict[str, Any], max_chars: int = DEFAULT_MAX_CHARS) -> list[dict[str, Any]]:
    """
    将文章切分为多个 chunk

    每个 chunk 包含固定头部（标题/时间/来源/导语）+ 正文片段，全部拼成一个字符串。

    Args:
        article: {
            "title": str,
            "pub_time": str,
            "source": str,
            "lead": str,  # 导语，可能为空
            "content": str,  # 完整正文（从 trafilatura 或 MinIO 读取）
        }
        max_chars: 每个 chunk 的最大字符数（估算：1 token ≈ 2 chars）

    Returns:
        list[{
            "chunk_index": int,
            "title": str,
            "pub_time": str,
            "source": str,
            "lead": str,
            "content": str,  # 固定头部 + 正文片段
            "content_hash": str,  # 当前 chunk 内容hash
        }]
    """
    title = article.get("title", "")
    pub_time = article.get("pub_time", "")
    source = article.get("source", "")
    lead = article.get("lead", "") or ""
    full_content = article.get("content", "")

    # 构建固定头部
    header_parts = [
        f"标题：{title}",
        f"发布时间：{pub_time}",
        f"来源：{source}",
    ]
    if lead:
        header_parts.append(f"导语：{lead}")

    header = "\n".join(header_parts) + "\n\n"
    header_len = len(header.encode("utf-8"))

    # 按 \n\n 切段落
    paragraphs = re.split(r"\n\n+", full_content)
    # 过滤空段落
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    chunks: list[dict[str, Any]] = []
    current_buffer: list[str] = []
    current_len = header_len

    def emit_chunk(buffer: list[str], idx: int) -> dict[str, Any]:
        """将 buffer 发射为一个 chunk"""
        body = "\n\n".join(buffer)
        content = header + body
        return {
            "chunk_index": idx,
            "title": title,
            "pub_time": pub_time,
            "source": source,
            "lead": lead,
            "content": content,
            "content_hash": make_content_hash(content),
        }

    for para in paragraphs:
        para_len = len(para.encode("utf-8"))

        # 如果单个段落就超过 max_chars，切碎它
        if para_len > max_chars:
            # 先发射当前 buffer
            if current_buffer:
                chunks.append(emit_chunk(current_buffer, len(chunks)))
                current_buffer = []
                current_len = header_len

            # 切分长段落（按句子或按固定长度）
            sentences = re.split(r"(?<=[。.!?？])\s+", para)
            for sent in sentences:
                sent_len = len(sent.encode("utf-8"))
                if current_len + sent_len > max_chars and current_buffer:
                    chunks.append(emit_chunk(current_buffer, len(chunks)))
                    current_buffer = []
                    current_len = header_len
                current_buffer.append(sent)
                current_len += sent_len
        else:
            # 正常段落
            if current_len + para_len > max_chars and current_buffer:
                chunks.append(emit_chunk(current_buffer, len(chunks)))
                current_buffer = []
                current_len = header_len

            current_buffer.append(para)
            current_len += para_len

    # 发射最后一个 buffer
    if current_buffer:
        chunks.append(emit_chunk(current_buffer, len(chunks)))

    logger.debug(
        "article_chunked",
        title=title[:50],
        num_chunks=len(chunks),
        total_chars=sum(len(c["content"]) for c in chunks),
    )

    return chunks