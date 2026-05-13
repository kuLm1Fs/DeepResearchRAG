#!/usr/bin/env python3
"""
RSS 增量采集脚本（支持断点续传）
用法:
    python rss_monitor.py                        # 交互模式
    python rss_monitor.py --all                  # 全量跑所有源
    python rss_monitor.py --resume               # 从断点继续
    python rss_monitor.py --source ifanr         # 只跑指定源
    python rss_monitor.py --source ifanr --limit 5  # 测试 5 篇
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
from vectorstore.embedding import embed_texts

CHECKPOINT_FILE = ROOT / "data" / "rss_monitor_checkpoint.json"
LOG_DIR = ROOT / "data" / "logs"

RSS_SOURCES = {
    "BBC World":     "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Reuters World": "https://www.reutersagency.com/feed/?best-topics=world-news&post_type=best",
    "TechCrunch":    "https://techcrunch.com/feed/",
    "The Verge":     "https://www.theverge.com/rss/index.xml",
    "Ars Technica":  "https://feeds.arstechnica.com/arstechnica/index",
    "36kr":          "https://36kr.com/feed",
    "少数派":         "https://sspai.com/feed",
    "钛媒体":         "https://www.tmtpost.com/feed",
    "ifanr":         "https://www.ifanr.com/feed",
    "澎湃新闻":       "https://www.thepaper.cn/rss",
}

CHUNK_MAX_CHARS = 1024
EMBED_BATCH_SIZE = 8


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


def process_source(name, state, force=False, logf=None, max_articles=None):
    url = RSS_SOURCES[name]
    source_state = state["sources"].setdefault(name, {
        "url": url,
        "processed_hashes": [],
        "articles_done": 0,
        "chunks_inserted": 0,
        "last_index": 0,
    })

    hashes = set(source_state["processed_hashes"])
    start_idx = source_state.get("last_index", 0) if not force else 0

    collector = RSSCollector()
    chunk_store = ChunkStore()
    minio_store = MinioStore()

    log(f"[{name}] 采集中 (从第 {start_idx} 篇开始) ...", logf)

    total_articles = 0
    processed = 0
    skipped = 0
    chunks_total = 0
    i = -1

    try:
        articles_iter = collector.collect_from_source(url, name, fetch_full_text=True)
        for i, article in enumerate(articles_iter):
            if max_articles and total_articles >= max_articles:
                break

            if i < start_idx:
                h = article.get("content_hash", "")
                if h:
                    hashes.add(h)
                continue

            total_articles += 1
            h = article.get("content_hash", "")

            if not force and h in hashes:
                skipped += 1
                continue

            content = article.get("content") or ""
            if len(content) < 100:
                continue

            # MinIO
            try:
                minio_store.upload_article(h, content)
            except Exception as e:
                log(f"  MinIO 跳过 ({h[:12]}): {e}", logf)
                continue

            # Chunk
            chunks = chunk_article(article, max_chars=CHUNK_MAX_CHARS)
            if not chunks:
                continue

            # Embed (小批量，快速)
            texts = [c["content"][:2000] for c in chunks]
            embeddings = embed_texts(texts, batch_size=EMBED_BATCH_SIZE)
            for c, emb in zip(chunks, embeddings):
                c["embedding"] = emb

            # 写入 Milvus
            try:
                chunk_store.insert_chunks(chunks)
                chunks_total += len(chunks)
                source_state["chunks_inserted"] += chunks_total
            except Exception as e:
                log(f"  Milvus 错误: {e}", logf)

            processed += 1
            hashes.add(h)

            if processed % 5 == 0:
                log(f"[{name}] 已处理 {processed} 篇 (chunks: {chunks_total})", logf)
                source_state["processed_hashes"] = list(hashes)[-2000:]
                source_state["last_index"] = i + 1
                save_checkpoint(state)

            del chunks, embeddings, texts, content
            gc.collect()

    except KeyboardInterrupt:
        source_state["last_index"] = i + 1
        save_checkpoint(state)
        raise
    except Exception as e:
        log(f"[{name}] 异常: {e}", logf)

    source_state["last_index"] = i + 1
    source_state["processed_hashes"] = list(hashes)[-2000:]
    source_state["articles_done"] += processed
    save_checkpoint(state)

    log(f"[{name}] ✅ 完成 (处理:{processed} 跳过:{skipped} chunks:{chunks_total})", logf)


def run_all_sources(force=False, max_per_source=None, logf=None):
    state = load_checkpoint()
    for name in RSS_SOURCES:
        log(f"\n{'='*50}\n {name}\n{'='*50}", logf)
        try:
            process_source(name, state, force=force, logf=logf, max_articles=max_per_source)
        except KeyboardInterrupt:
            save_checkpoint(state)
            log("中断，已保存断点", logf)
            raise
        except Exception as e:
            log(f"[{name}] 异常: {e}", logf)
            continue
    save_checkpoint(state)


def run_resume(max_per_source=None, logf=None):
    state = load_checkpoint()
    done = [n for n in RSS_SOURCES if n in state["sources"]]
    pending = [n for n in RSS_SOURCES if n not in state["sources"]]
    log(f"已完成: {', '.join(done) or '无'}", logf)
    log(f"待处理: {', '.join(pending) or '无'}", logf)
    for name in pending:
        log(f"\n{'='*50}\n {name}\n{'='*50}", logf)
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
    parser.add_argument("--source")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    ensure_dir(LOG_DIR)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"rss_{ts}.log"

    with open(log_file, "a", encoding="utf-8") as logf:
        log(f"=== RSS Monitor 启动 ===", logf)
        log(f"Log: {log_file}", logf)
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
                    print(f"  {i}. {name} ({done} 篇)")
                choice = input("\n输入源名: ").strip()
                if choice in RSS_SOURCES:
                    process_source(choice, state, logf=logf)
                    save_checkpoint(state)
        except KeyboardInterrupt:
            log("用户中断", logf)