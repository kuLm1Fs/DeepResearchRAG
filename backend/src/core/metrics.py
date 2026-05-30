from collections import defaultdict
from threading import Lock


class MetricsRegistry:
    """Small in-process counter registry with Prometheus text rendering."""

    def __init__(self):
        self._counters: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def render_prometheus(self) -> str:
        lines = [
            "# TYPE rag_app_info gauge",
            'rag_app_info{app="rag-news-intelligence"} 1',
        ]
        with self._lock:
            for name in sorted(self._counters):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {self._counters[name]}")
        return "\n".join(lines) + "\n"


metrics_registry = MetricsRegistry()
