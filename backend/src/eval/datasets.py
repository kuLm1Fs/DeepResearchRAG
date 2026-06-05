"""Evaluation dataset loading for golden cases and badcase regression."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None and str(item)]
    raise ValueError("expected a string or list of strings")


def _as_dict_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of objects")
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"{field_name} must be a list of objects")
        items.append(dict(item))
    return items


def _as_dict(value: Any, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return dict(value)


def _normalise_case(raw: dict[str, Any], case_number: int, source: Path) -> dict[str, Any]:
    query = raw.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f"{source.name}:{case_number} missing required field: query")

    try:
        expected_sources = _as_string_list(raw.get("expected_sources"))
        if not expected_sources and raw.get("doc_name"):
            expected_sources = _as_string_list(raw.get("doc_name"))
        required_sources = _as_string_list(raw.get("required_sources"))
        if not required_sources:
            required_sources = list(expected_sources)
        expected_keywords = _as_string_list(raw.get("expected_keywords"))
        expected_evidence = _as_dict_list(raw.get("expected_evidence"), "expected_evidence")
        expected_numbers = _as_dict_list(raw.get("expected_numbers"), "expected_numbers")
        temporal_constraints = _as_dict(raw.get("temporal_constraints"), "temporal_constraints")
    except ValueError as exc:
        raise ValueError(f"{source.name}:{case_number} {exc}") from exc

    failure_type = str(raw.get("failure_type", "") or "")
    case_type = str(raw.get("case_type", "") or "")
    if not case_type:
        case_type = "badcase" if failure_type else "golden"

    return {
        "id": str(raw.get("id") or f"case-{case_number:03d}"),
        "query": query.strip(),
        "query_type": str(raw.get("query_type", "general") or "general"),
        "expected_sources": expected_sources,
        "required_sources": required_sources,
        "expected_evidence": expected_evidence,
        "expected_numbers": expected_numbers,
        "temporal_constraints": temporal_constraints,
        "expected_keywords": expected_keywords,
        "gold_answer": str(raw.get("gold_answer", "") or ""),
        "difficulty": str(raw.get("difficulty", "unknown") or "unknown"),
        "category": str(raw.get("category", "") or ""),
        "case_type": case_type,
        "failure_type": failure_type,
        "expected_behavior": str(raw.get("expected_behavior", "") or ""),
    }


def _load_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict) and isinstance(data.get("queries"), list):
        return data["queries"]
    if isinstance(data, list):
        return data
    raise ValueError(f"{path.name} must be a JSON array or an object with queries[]")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_number} invalid JSON") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"{path.name}:{line_number} must be a JSON object")
            cases.append(_normalise_case(raw, line_number, path))
    return cases


def load_eval_cases(path: Path) -> list[dict[str, Any]]:
    """Load finance eval cases from JSON or JSONL.

    Supported formats:
    - JSON object with ``queries`` list, as produced by build_financebench_eval.py
    - JSON list of cases
    - JSONL, one case per line, convenient for manually curated badcases
    """
    if path.suffix == ".jsonl":
        return _load_jsonl(path)

    raw_cases = _load_json(path)
    cases = []
    for index, raw in enumerate(raw_cases, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{path.name}:{index} must be a JSON object")
        cases.append(_normalise_case(raw, index, path))
    return cases


def split_eval_cases(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split normalized cases into golden cases and badcase regressions."""
    golden = [case for case in cases if case.get("case_type") != "badcase"]
    badcases = [case for case in cases if case.get("case_type") == "badcase"]
    return golden, badcases
