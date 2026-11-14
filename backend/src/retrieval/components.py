"""Switches for retrieval stages.

Defaults match the production pipeline: every Milvus path, RRF, time decay,
source weighting, the reranker, and the graph path when a graph retriever
is attached. Pass a non-default ``RetrievalComponents`` to turn stages off.
``ABLATION_PRESETS`` are the FinanceBench ablation matrix; they are not used
unless a caller selects them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetrievalComponents:
    """Which retrieval stages to run.

    ``bm25`` is the existing keyword/fulltext path (Milvus LIKE over title
    and content). The repository does not compute a separate BM25 score.
    """

    vector: bool = True
    bm25: bool = True
    title: bool = True
    rrf: bool = True
    reranker: bool = True
    time_decay: bool = True
    source_weight: bool = True
    graph: bool = True

    def as_dict(self) -> dict[str, bool]:
        return {
            "vector": self.vector,
            "bm25": self.bm25,
            "title": self.title,
            "rrf": self.rrf,
            "reranker": self.reranker,
            "time_decay": self.time_decay,
            "source_weight": self.source_weight,
            "graph": self.graph,
        }

    @classmethod
    def from_settings(cls, config: Any) -> RetrievalComponents:
        """Read optional ``retrieval_*`` settings. Missing attributes stay on."""

        def flag(name: str) -> bool:
            return bool(getattr(config, name, True))

        return cls(
            vector=flag("retrieval_vector"),
            bm25=flag("retrieval_bm25"),
            title=flag("retrieval_title"),
            rrf=flag("retrieval_rrf"),
            reranker=flag("retrieval_reranker"),
            time_decay=flag("retrieval_time_decay"),
            source_weight=flag("retrieval_source_weight"),
            graph=flag("retrieval_graph"),
        )


def _preset(**overrides: bool) -> RetrievalComponents:
    """Ablation preset: every stage off unless ``overrides`` turns it on."""
    base = dict(
        vector=False,
        bm25=False,
        title=False,
        rrf=False,
        reranker=False,
        time_decay=False,
        source_weight=False,
        graph=False,
    )
    base.update(overrides)
    return RetrievalComponents(**base)


# Graph stays off in every preset so the matrix compares the three Milvus
# paths. Production still attaches the graph retriever when graph_enabled.
ABLATION_PRESETS: dict[str, RetrievalComponents] = {
    "vector": _preset(vector=True),
    "bm25": _preset(bm25=True),
    "title": _preset(title=True),
    "vector_bm25": _preset(vector=True, bm25=True, rrf=True),
    "vector_bm25_title": _preset(vector=True, bm25=True, title=True, rrf=True),
    "full": _preset(
        vector=True,
        bm25=True,
        title=True,
        rrf=True,
        reranker=True,
        time_decay=True,
        source_weight=True,
    ),
}

ABLATION_LABELS: dict[str, str] = {
    "vector": "vector only",
    "bm25": "bm25 only",
    "title": "title only",
    "vector_bm25": "vector+bm25 (RRF)",
    "vector_bm25_title": "vector+bm25+title (RRF)",
    "full": "full (RRF + time decay + source weight + reranker)",
}

ABLATION_CONFIG_NAMES: tuple[str, ...] = tuple(ABLATION_PRESETS)

_CONFIG_ALIASES = {
    "vector": "vector",
    "vector_only": "vector",
    "bm25": "bm25",
    "bm25_only": "bm25",
    "keyword": "bm25",
    "title": "title",
    "title_only": "title",
    "vector_bm25": "vector_bm25",
    "vector+bm25": "vector_bm25",
    "vector_bm25_rrf": "vector_bm25",
    "vector_bm25_title": "vector_bm25_title",
    "vector+bm25+title": "vector_bm25_title",
    "vector_bm25_title_rrf": "vector_bm25_title",
    "full": "full",
    "full_reranker": "full",
    "full_pipeline": "full",
}


def parse_ablation_configs(raw: str | None) -> list[str]:
    """Parse a comma-separated config list. ``None`` selects the full matrix."""
    if raw is None or not raw.strip():
        return list(ABLATION_CONFIG_NAMES)

    selected: list[str] = []
    unknown: list[str] = []
    for piece in raw.split(","):
        name = piece.strip().lower()
        if not name:
            continue
        canonical = _CONFIG_ALIASES.get(name)
        if canonical is None:
            unknown.append(piece.strip())
            continue
        if canonical not in selected:
            selected.append(canonical)
    if unknown:
        known = ", ".join(ABLATION_CONFIG_NAMES)
        raise ValueError(f"unknown ablation config: {', '.join(unknown)}. Known: {known}")
    if not selected:
        raise ValueError("no ablation configs selected")
    return selected
