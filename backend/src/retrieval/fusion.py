from typing import Any


def reciprocal_rank_fusion(
    result_lists: list[list[dict[str, Any]]],
    weights: list[float] | None = None,
    k: int = 60,
) -> list[dict[str, Any]]:
    """
    Reciprocal Rank Fusion (RRF) algorithm.

    Combines multiple ranked result lists into a single ranked list.

    Args:
        result_lists: List of result lists from different retrieval paths
        weights: Optional weights for each list (default: equal weights)
        k: RRF constant (default: 60)

    Returns:
        Fused and reranked results
    """
    if not result_lists:
        return []

    if weights is None:
        weights = [1.0] * len(result_lists)
    elif len(weights) != len(result_lists):
        raise ValueError("Number of weights must match number of result lists")

    # Normalize weights
    total_weight = sum(weights)
    weights = [w / total_weight for w in weights]

    # Score each document
    doc_scores: dict[str, tuple[float, dict[str, Any]]] = {}

    for result_list, weight in zip(result_lists, weights):
        for rank, doc in enumerate(result_list, start=1):
            # Use content_hash or id as unique key
            doc_key = doc.get("content_hash") or str(doc.get("id", rank))

            # RRF score with weight
            rrf_score = weight * (1 / (k + rank))

            if doc_key in doc_scores:
                existing_score, existing_doc = doc_scores[doc_key]
                doc_scores[doc_key] = (existing_score + rrf_score, existing_doc)
            else:
                doc_scores[doc_key] = (rrf_score, doc)

    # Sort by combined score
    sorted_docs = sorted(doc_scores.values(), key=lambda x: x[0], reverse=True)

    # Return merged documents with fused scores
    fused_results = []
    for score, doc in sorted_docs:
        result = dict(doc)
        result["fused_score"] = score
        fused_results.append(result)

    return fused_results


# Alias for backward compatibility
fusion = reciprocal_rank_fusion