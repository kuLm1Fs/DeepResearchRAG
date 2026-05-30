"""Optional CrossEncoder reranking for fused retrieval results."""
from __future__ import annotations

from typing import Any

from core import get_logger

logger = get_logger(__name__)


class CrossEncoderReranker:
    """Rerank query/document pairs with sentence-transformers when installed."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-v2-m3"):
        self.model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name)
            return self._model
        except Exception as exc:
            logger.warning("cross_encoder_unavailable", model=self.model_name, error=str(exc))
            return None

    def rerank(self, query: str, results: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        if not results:
            return []

        model = self._load_model()
        if model is None:
            return self._fallback_rerank(query, results, top_k)

        pairs = [(query, _document_text(result)) for result in results]
        scores = model.predict(pairs)
        reranked = []
        for result, score in zip(results, scores):
            item = dict(result)
            item["rerank_score"] = float(score)
            reranked.append(item)
        return sorted(reranked, key=lambda item: item.get("rerank_score", 0.0), reverse=True)[:top_k]

    def _fallback_rerank(
        self,
        query: str,
        results: list[dict[str, Any]],
        top_k: int,
    ) -> list[dict[str, Any]]:
        terms = {term.lower() for term in query.split() if term.strip()}
        reranked = []
        for result in results:
            text = _document_text(result).lower()
            lexical_hits = sum(1 for term in terms if term in text)
            item = dict(result)
            item["rerank_score"] = item.get("fused_score", item.get("score", 0.0)) + lexical_hits * 0.05
            item["rerank_mode"] = "lexical_fallback"
            reranked.append(item)
        return sorted(reranked, key=lambda item: item.get("rerank_score", 0.0), reverse=True)[:top_k]


def _document_text(result: dict[str, Any]) -> str:
    return f"{result.get('title', '')}\n{result.get('content', '')}"[:4000]
