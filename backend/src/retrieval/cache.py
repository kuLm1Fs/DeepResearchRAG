"""Disk cache for per-path retrieval results.

A hit returns the documents from the first successful call and the latency
measured on that call. Read time is not treated as retrieval latency.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


class RetrievalPathCache:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def get(
        self,
        path: str,
        query: str,
        filter_expr: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], float] | None:
        file = self._file(path, query, filter_expr, limit)
        if not file.exists():
            return None
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            results = data["results"]
            latency_ms = float(data["latency_ms"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(results, list):
            return None
        return [dict(item) for item in results if isinstance(item, dict)], latency_ms

    def put(
        self,
        path: str,
        query: str,
        filter_expr: str | None,
        limit: int,
        results: list[dict[str, Any]],
        latency_ms: float,
    ) -> None:
        payload = {
            "path": path,
            "query": query,
            "filter": filter_expr,
            "limit": limit,
            "latency_ms": latency_ms,
            "results": results,
        }
        try:
            encoded = json.dumps(payload, ensure_ascii=False)
        except TypeError:
            return
        file = self._file(path, query, filter_expr, limit)
        temporary = file.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(file)

    def _file(self, path: str, query: str, filter_expr: str | None, limit: int) -> Path:
        raw = json.dumps(
            {
                "path": path,
                "query": query,
                "filter": filter_expr or "",
                "limit": limit,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(raw.encode()).hexdigest()
        return self.directory / f"{digest}.json"
