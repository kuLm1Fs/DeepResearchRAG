#!/usr/bin/env python3
"""Run the reliable Deep Research worker.

The worker uses the database as durable state and can be paired with Redis as
a wake-up queue. If Redis is unavailable, polling pending/stale DB tasks still
prevents task loss.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core import configure_logging, get_logger
from tasks.research import run_research_worker_once

configure_logging()
logger = get_logger(__name__)


async def main_async(args: argparse.Namespace) -> int:
    worker_id = args.worker_id or f"research-worker-{uuid.uuid4().hex[:8]}"
    logger.info("research_worker_started", worker_id=worker_id)

    while True:
        processed = await run_research_worker_once(
            worker_id=worker_id,
            heartbeat_timeout_seconds=args.heartbeat_timeout,
        )
        if args.once:
            return 0
        if not processed:
            await asyncio.sleep(args.poll_interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run reliable Deep Research worker")
    parser.add_argument("--worker-id", default=os.getenv("WORKER_ID"))
    parser.add_argument("--once", action="store_true", help="Process at most one task and exit")
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--heartbeat-timeout", type=int, default=120)
    return parser


def main() -> int:
    return asyncio.run(main_async(build_parser().parse_args()))


if __name__ == "__main__":
    sys.exit(main())
