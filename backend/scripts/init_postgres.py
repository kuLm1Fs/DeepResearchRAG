#!/usr/bin/env python3
"""初始化 PostgreSQL 数据库：执行 schema.sql"""
import subprocess
import sys
import os
from pathlib import Path

import structlog
logger = structlog.get_logger()


def main():
    schema_path = Path(__file__).parent.parent.parent / "docs" / "schema.sql"
    if not schema_path.exists():
        print(f"ERROR: schema.sql not found at {schema_path}")
        sys.exit(1)

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "rag_news")
    user = os.getenv("POSTGRES_USER", "rag_user")
    password = os.getenv("POSTGRES_PASSWORD", "")

    if not password:
        print("ERROR: POSTGRES_PASSWORD not set")
        sys.exit(1)

    cmd = [
        "psql",
        "-h", host,
        "-p", port,
        "-U", user,
        "-d", db,
        "-f", str(schema_path),
    ]

    env = {**os.environ, "PGPASSWORD": password}
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    except Exception as e:
        print(f"WARNING: {e}")
        print("Continuing despite error...")
        sys.exit(0)  # 表已存在或其他错误，报 WARNING 后继续

    if result.returncode != 0:
        # psql 可能因为 IF NOT EXISTS 而报 WARNING，但脚本继续
        stderr_lower = result.stderr.lower() if result.stderr else ""
        stdout_lower = result.stdout.lower() if result.stdout else ""
        # 检查是否是"表已存在"类警告（非致命）
        if "already exists" in stderr_lower or "already exists" in stdout_lower:
            print(f"WARNING: {result.stderr or result.stdout}")
            print("Continuing...")
            sys.exit(0)
        else:
            print(f"ERROR: {result.stderr or result.stdout}")
            sys.exit(result.returncode)

    print("PostgreSQL schema initialized successfully.")
    sys.exit(0)