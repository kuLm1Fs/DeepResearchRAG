#!/usr/bin/env python3
"""
RSS 增量采集脚本（支持断点续传）
用法:
    python rss_monitor.py                    # 交互模式
    python rss_monitor.py --all              # 全量跑所有源
    python rss_monitor.py --resume           # 从断点继续
    python rss_monitor.py --source techcrunch # 只跑指定源
"""

import argparse
import gc
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "src"))

from ingestion.rss_collector import RSSCollector
from ingestion.chunker import chunk_article
from storage import MinioStore
from vectorstore.chunk_store import ChunkStore
from vectorstore.embedding import embed_texts_async

CHECKPOINT_FILE = ROOT / "data" / "rss_monitor_checkpoint.json"
LOG_DIR = ROOT / "data" / "logs"

RSS_SOURCES = {
    "bbc":         "https://feeds.bbci.co.uk/news/world/rss.xml",
    "reuters":     "https://www.reutersagency.com/feed/?best-topics=world-news&post_type=best",
    "techcrunch":   "https://techcrunch.com/feed/",
    "theverge":     "https://www.theverge.com/rss/index.xml",
    "ars":          "https://feeds.arstechnica.com/arstechnica/index",
    "36kr":         "https://36kr.com/feed",
    "sspai":        "https://sspai.com/feed",
    "tmtpost":      "https://www.tmtpost.com/feed",
    "ifanr":        "https://www.ifanr.com/feed",
    "thepaper":     "https://www.thepaper.cn/rss",
}

CHUNK_MAX_CHARS = 1024
BATCH_SIZE = 16


def ensure_dir(path):
    path.mkdir(parents=True, exist_ok=True)


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"sources": {}, "last_updated": None}


def save_checkpoint(state):
    state["last_updated"] = datetime.now().isoformat()
    ensure_dir(CHECKPOINT_FILE.parent)
    CHECKPOINT_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def log(msg, file=None):
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    if file:
        file.write(line + "\n")
        file.flush()


def process_article(article, chunk_store, minio_store, source_state):
    """处理单篇文章，返回插入 chunk 数"""
    content_hash = article.get("content_hash") or article.get("hash")
    if not content_hash:
        return 0

    full_text = article.get("full_text") or article.get("text", "")
    if not full_text or len(full_text) < 100:
        return 0

    # MinIO 存储
    try:
        minio_store.upload_article(content_hash, full_text)
    except Exception as e:
        print(f"  MinIO upload failed: {e}")
        return 0

    # Chunk
    chunks = chunk_article(article, max_chars=CHUNK_MAX_CHARS)
    if not chunks:
        return 0

    # Embed (batch)
    chunk_texts = [c["content"] for c in chunks]
    embeddings = embed_texts_async(chunk_texts, batch_size=BATCH_SIZE)

    # 写入 Milvus
    inserted = 0
    for chunk, emb in zip(chunks, embeddings):
        try:
            chunk_store.upsert_chunk(chunk, emb)
            inserted += 1
        except Exception as e:
            print(f"  Milvus upsert failed: {e}")

    del chunk_texts, embeddings, chunks, full_text
    gc.collect()

    return inserted


def process_source(name, state, force=False, logf=None, max_articles=None):
    url = RSS_SOURCES[name]
    source_state = state["sources"].setdefault(name, {
        "url": url,
        "processed_hashes": [],
        "articles_done": 0,
        "chunks_inserted": 0,
        "last_article_index": 0,
    })

    processed_hashes = set(source_state["processed_hashes"])
    start_idx = source_state.get("last_article_index", 0) if not force else 0

    collector = RSSCollector()

    log(f"[{name}] 开始采集 (断点: 第 {start_idx} 篇)", logf)
    try:
        articles_iter = collector.collect_from_source(
            url, name, fetch_full_text=True
        )
    except Exception as e:
        log(f"[{name}] RSS 获取失败: {e}", logf)
        return

    chunk_store = ChunkStore()
    minio_store = MinioStore()
    processed = 0
    skipped = 0
    inserted_total = 0

    # 流式处理，逐条迭代
    for i, article in enumerate(articles_iter):
        if max_articles and i >= max_articles:
            break

        if i < start_idx:
            # 跳过已处理
            h = article.get("content_hash") or article.get("hash", "")
            if h:
                processed_hashes.add(h)
            continue

        if i % 20 == 0:
            log(f"[{name}] 进度 {i} ...", logf)

        h = article.get("content_hash") or article.get("hash", "")

        if not force and h in processed_hashes:
            skipped += 1
            continue

        inserted = process_article(article, chunk_store, minio_store, source_state)
        processed += 1
        if h:
            processed_hashes.add(h)

        if inserted > 0:
            source_state["articles_done"] += 1
            source_state["chunks_inserted"] += inserted_total + inserted
            inserted_total += inserted

        # 每处理10篇保存一次断点
        if processed > 0 and processed % 10 == 0:
            source_state["last_article_index"] = i + 1
            source_state["processed_hashes"] = list(processed_hashes)[-3000:]
            save_checkpoint(state)

    # 最终保存
    source_state["last_article_index"] = i + 1
    source_state["processed_hashes"] = list(processed_hashes)[-3000:]
    save_checkpoint(state)

    log(f"[{name}] ✅ 完成 (处理:{processed} 跳过:{skipped} chunks:{inserted_total})", logf)


def run_all_sources(force=False, max_per_source=None, logf=None):
    state = load_checkpoint()
    for name in RSS_SOURCES:
        log(f"\n{'='*50}\n 处理源: {name}\n{'='*50}", logf)
        try:
            process_source(name, state, force=force, logf=logf, max_articles=max_per_source)
        except KeyboardInterrupt:
            save_checkpoint(state)
            log("中断，已保存断点，可 --resume 继续", logf)
            raise
        except Exception as e:
            log(f"[{name}] 异常: {e}", logf)
            continue
    save_checkpoint(state)


def run_resume(max_per_source=None, logf=None):
    state = load_checkpoint()
    if not state["sources"]:
        log("无断点记录，先运行 --all", logf)
        return

    pending = [n for n in RSS_SOURCES if n not in state["sources"]]
    done = [n for n in RSS_SOURCES if n in state["sources"]]
    log(f"已完成: {', '.join(done) or '无'}", logf)
    log(f"待处理: {', '.join(pending) or '无'}", logf)

    for name in pending:
        log(f"\n{'='*50}\n 继续: {name}\n{'='*50}", logf)
        try:
            process_source(name, state, force=False, logf=logf, max_articles=max_per_source)
        except KeyboardInterrupt:
            save_checkpoint(state)
            log("中断，已保存断点", logf)
            raise
        except Exception as e:
            log(f"[{name}] 异常: {e}", logf)
            continue
    save_checkpoint(state)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--source", help="源名称，如 techcrunch")
    parser.add_argument("--limit", type=int, help="每个源最多处理篇数（测试用）")
    args = parser.parse_args()

    ensure_dir(LOG_DIR)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"rss_{ts}.log"

    with open(log_file, "a", encoding="utf-8") as logf:
        log(f"=== RSS Monitor 启动 ===", logf)
        try:
            if args.all:
                run_all_sources(force=args.force, max_per_source=args.limit, logf=logf)
            elif args.resume:
                run_resume(max_per_source=args.limit, logf=logf)
            elif args.source:
                state = load_checkpoint()
                process_source(args.source, state, force=args.force, logf=logf, max_articles=args.limit)
                save_checkpoint(state)
            else:
                state = load_checkpoint()
                print("\n可用源:")
                for i, name in enumerate(RSS_SOURCES, 1):
                    done = state["sources"].get(name, {}).get("articles_done", 0)
                    print(f"  {i}. {name} ({done} 篇已处理)")
                choice = input("\n输入源名或 all: ").strip()
                if choice == "all":
                    run_all_sources(logf=logf)
                elif choice in RSS_SOURCES:
                    process_source(choice, state, logf=logf)
                    save_checkpoint(state)
        except KeyboardInterrupt:
            log("用户中断，退出", logf)