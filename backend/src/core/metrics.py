from collections import defaultdict
from collections.abc import Iterable
from threading import Lock

LabelKey = tuple[tuple[str, str], ...]
MetricKey = tuple[str, LabelKey]


class MetricsRegistry:
    """Small in-process metrics registry with Prometheus text rendering.

    This is intentionally tiny: it gives the app low-cardinality counters,
    gauges, and histograms without pulling in a metrics server dependency.
    The public methods mirror Prometheus concepts so this can be swapped for
    prometheus_client later with minimal call-site churn.
    """

    def __init__(self):
        self._counters: dict[MetricKey, float] = defaultdict(float)
        self._gauges: dict[MetricKey, float] = {}
        self._histograms: dict[MetricKey, dict] = {}
        self._lock = Lock()

    def increment(self, name: str, amount: float = 1, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._counters[(name, _label_key(labels))] += amount

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._gauges[(name, _label_key(labels))] = value

    def observe(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
        buckets: Iterable[float] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    ) -> None:
        bucket_tuple = tuple(sorted(float(bucket) for bucket in buckets))
        key = (name, _label_key(labels))
        with self._lock:
            histogram = self._histograms.setdefault(
                key,
                {
                    "buckets": bucket_tuple,
                    "counts": {bucket: 0 for bucket in bucket_tuple},
                    "inf": 0,
                    "count": 0,
                    "sum": 0.0,
                },
            )
            if histogram["buckets"] != bucket_tuple:
                raise ValueError(f"Histogram {name} observed with inconsistent buckets")

            histogram["count"] += 1
            histogram["sum"] += value
            histogram["inf"] += 1
            for bucket in bucket_tuple:
                if value <= bucket:
                    histogram["counts"][bucket] += 1

    def render_prometheus(self) -> str:
        lines = [
            "# TYPE rag_app_info gauge",
            'rag_app_info{app="rag-finance-intelligence"} 1',
        ]
        with self._lock:
            for (name, labels), value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name}{_format_labels(labels)} {_format_number(value)}")

            for (name, labels), value in sorted(self._gauges.items()):
                lines.append(f"# TYPE {name} gauge")
                lines.append(f"{name}{_format_labels(labels)} {_format_number(value)}")

            for (name, labels), histogram in sorted(self._histograms.items()):
                lines.append(f"# TYPE {name} histogram")
                for bucket in histogram["buckets"]:
                    bucket_labels = (*labels, ("le", _format_bucket(bucket)))
                    lines.append(
                        f"{name}_bucket{_format_labels(bucket_labels)} "
                        f"{histogram['counts'][bucket]}"
                    )
                inf_labels = (*labels, ("le", "+Inf"))
                lines.append(f"{name}_bucket{_format_labels(inf_labels)} {histogram['inf']}")
                lines.append(f"{name}_count{_format_labels(labels)} {histogram['count']}")
                lines.append(
                    f"{name}_sum{_format_labels(labels)} "
                    f"{_format_number(histogram['sum'])}"
                )
        return "\n".join(lines) + "\n"


metrics_registry = MetricsRegistry()


def _label_key(labels: dict[str, str] | None) -> LabelKey:
    if not labels:
        return ()
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def _format_labels(labels: LabelKey) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{key}="{_escape_label_value(value)}"' for key, value in labels)
    return f"{{{rendered}}}"


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6g}"


def _format_bucket(value: float) -> str:
    if float(value).is_integer():
        return f"{value:.1f}"
    return f"{value:.6g}"
