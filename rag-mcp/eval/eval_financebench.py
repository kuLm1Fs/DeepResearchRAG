#!/usr/bin/env python3
"""Compare FinanceBench evidence hit rate and answer quality with and without MCP retrieval.

The script never invents scores. If the MCP server cannot be reached, or a
search call fails because Milvus or the embedding API is unavailable, it
prints NOT RUN and exits 2. A results file is written only after real calls
succeed.

Answer quality is measured only when an OpenAI-compatible key is set
(DEEPSEEK_API_KEY or OPENAI_API_KEY). Otherwise that section is reported as
not measured, and evidence hit rate is still reported if retrieval ran.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend" / "src"
DEFAULT_DATASET = ROOT / "backend" / "data" / "eval_financebench.json"


def evidence_hit_at_k(results: list[dict[str, Any]], expected: list[dict[str, Any]], k: int) -> float:
    """Local copy of the repo metric so the script can run beside the backend."""
    if not expected or k <= 0:
        return 0.0
    hits = 0
    for item in expected:
        source = _norm(item.get("source_id", ""))
        terms = [str(term).lower() for term in item.get("must_contain", []) if str(term)]
        for result in results[:k]:
            blob = " ".join(
                str(result.get(field, "") or "")
                for field in ("title", "content", "source", "url", "doc_id")
            ).lower()
            if source and source not in _norm(blob) and not any(source in _norm(str(result.get(field, ""))) for field in ("title", "source", "url", "doc_id")):
                continue
            if terms and not all(term.lower() in blob for term in terms):
                continue
            hits += 1
            break
    return hits / len(expected)


def gold_numbers(gold: str) -> list[str]:
    raw = gold.replace(",", "")
    found = []
    for match in re.findall(r"\d+(?:\.\d+)?", raw):
        whole = match.split(".", 1)[0]
        if re.fullmatch(r"(?:19|20)\d\d", whole) and "." not in match:
            continue
        found.append(match)
    return found


def _number_forms(number: str) -> set[str]:
    forms = {number.lower()}
    try:
        value = float(number)
    except ValueError:
        return forms
    forms.add(f"{value:g}".lower())
    if value.is_integer():
        forms.add(str(int(value)))
    return forms


def answer_contains_gold(answer: str, gold: str) -> float:
    if not answer or not gold:
        return 0.0
    folded = answer.replace(",", "").lower()
    numbers = gold_numbers(gold)
    if not numbers:
        return 1.0 if gold.strip().lower() in folded else 0.0
    forms = set()
    for number in numbers:
        forms |= _number_forms(number)
    return 1.0 if any(form and form in folded for form in forms) else 0.0


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


class MCPError(RuntimeError):
    pass


class MCPClient:
    """Small Streamable HTTP client for the eval. Not a general MCP library."""

    def __init__(self, url: str, token: str, timeout: float = 60):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id = ""
        self._next_id = 1

    def initialize(self) -> None:
        result = self._rpc("initialize", {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "rag-mcp-eval", "version": "0.1.0"},
        })
        if "serverInfo" not in result and "protocolVersion" not in result:
            raise MCPError(f"unexpected initialize result: {result}")
        self._notify("notifications/initialized", {})

    def search(self, query: str, top_k: int, rewrite: bool) -> list[dict[str, Any]]:
        result = self._rpc("tools/call", {
            "name": "search",
            "arguments": {"query": query, "top_k": top_k, "rewrite": rewrite},
        })
        if result.get("isError"):
            raise MCPError(_text_content(result) or "search tool returned an error")
        payload = result.get("structuredContent")
        if not isinstance(payload, dict):
            text = _text_content(result)
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise MCPError(f"search returned unreadable content: {text[:200]}") from exc
        results = payload.get("results") or []
        if not isinstance(results, list):
            raise MCPError("search results were not a list")
        return results

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params}, expect_body=False)

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        message = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        self._next_id += 1
        body = self._post(message, expect_body=True)
        if "error" in body:
            raise MCPError(str(body["error"]))
        result = body.get("result")
        if not isinstance(result, dict):
            raise MCPError(f"{method} returned no result")
        return result

    def _post(self, payload: dict[str, Any], expect_body: bool) -> dict[str, Any]:
        data = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
                if session:
                    self.session_id = session
                raw = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise MCPError(f"HTTP {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"cannot reach MCP server: {exc.reason}") from exc
        if not expect_body:
            return {}
        return _decode_mcp_body(raw, content_type)


def _decode_mcp_body(raw: str, content_type: str) -> dict[str, Any]:
    if "text/event-stream" in content_type or raw.lstrip().startswith("event:") or raw.lstrip().startswith("data:"):
        decoded = None
        for line in raw.splitlines():
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if not chunk or chunk == "[DONE]":
                continue
            decoded = json.loads(chunk)
        if not isinstance(decoded, dict):
            raise MCPError("empty event stream from MCP server")
        return decoded
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise MCPError("MCP response was not an object")
    return body


def _text_content(result: dict[str, Any]) -> str:
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("text"):
            parts.append(str(item["text"]))
    return "\n".join(parts)


def load_cases(path: Path, limit: int) -> list[dict[str, Any]]:
    document = json.loads(path.read_text())
    queries = document.get("queries") or document
    if not isinstance(queries, list):
        raise SystemExit(f"dataset {path} has no queries list")
    if limit > 0:
        queries = queries[:limit]
    return queries


def chat(base_url: str, api_key: str, model: str, prompt: str, timeout: float) -> str:
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [{"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode())
    return body["choices"][0]["message"]["content"]


def llm_settings() -> tuple[str, str, str] | None:
    if os.getenv("DEEPSEEK_API_KEY"):
        return (
            os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            os.environ["DEEPSEEK_API_KEY"],
            os.getenv("DEEPSEEK_MODEL", os.getenv("LLM_MODEL", "deepseek-chat")),
        )
    if os.getenv("OPENAI_API_KEY"):
        return (
            os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            os.environ["OPENAI_API_KEY"],
            os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )
    return None


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def run_self_check() -> int:
    hit = evidence_hit_at_k(
        [{"content": "net income 5363 in 2018", "source": "3M_2018_10K", "title": "", "doc_id": "d"}],
        [{"source_id": "3M_2018_10K", "must_contain": ["2018", "net income"]}],
        5,
    )
    if hit != 1.0:
        print("self-check failed: evidence hit", file=sys.stderr)
        return 1
    if answer_contains_gold("The amount is $1,577 million.", "$1577.00") != 1.0:
        print("self-check failed: gold match", file=sys.stderr)
        return 1
    if answer_contains_gold("I do not know.", "$1577.00") != 0.0:
        print("self-check failed: gold miss", file=sys.stderr)
        return 1
    print("self-check ok (no benchmark was run)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=20, help="How many FinanceBench questions to score. 0 means all.")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--mcp-url", default=os.getenv("RAG_MCP_URL", "http://127.0.0.1:8081/mcp"))
    parser.add_argument("--token", default=os.getenv("MCP_BEARER_TOKEN", ""))
    parser.add_argument("--rewrite", action="store_true", help="Enable query rewriting during search.")
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--out", type=Path, default=None, help="Write the measured report here. Omitted unless a run finishes.")
    parser.add_argument("--self-check", action="store_true", help="Check the metric helpers. Does not contact a server and does not produce a score.")
    args = parser.parse_args()

    if args.self_check:
        return run_self_check()
    if not args.token:
        print("NOT RUN: set --token or MCP_BEARER_TOKEN. No scores were computed.", file=sys.stderr)
        return 2
    if not args.dataset.exists():
        print(f"NOT RUN: dataset not found at {args.dataset}. No scores were computed.", file=sys.stderr)
        return 2

    cases = load_cases(args.dataset, args.limit)
    if not cases:
        print("NOT RUN: dataset has no queries. No scores were computed.", file=sys.stderr)
        return 2
    client = MCPClient(args.mcp_url, args.token, timeout=args.timeout)
    try:
        client.initialize()
        probe = client.search(cases[0]["query"], args.top_k, args.rewrite)
    except MCPError as exc:
        print(f"NOT RUN: {exc}. No scores were computed.", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"NOT RUN: {exc}. No scores were computed.", file=sys.stderr)
        return 2

    llm = llm_settings()
    rows = []
    evidence_hits = []
    with_gold = []
    without_gold = []
    first = True
    for case in cases:
        query = case["query"]
        try:
            results = probe if first else client.search(query, args.top_k, args.rewrite)
        except MCPError as exc:
            print(f"NOT RUN: search failed on {case.get('id')}: {exc}. Partial scores were discarded.", file=sys.stderr)
            return 2
        first = False
        hit = evidence_hit_at_k(results, case.get("expected_evidence") or [], args.top_k)
        evidence_hits.append(hit)
        row: dict[str, Any] = {
            "id": case.get("id"),
            "evidence_hit": hit,
            "retrieved": len(results),
        }
        if llm is not None:
            base_url, api_key, model = llm
            evidence = "\n\n".join(
                f"[{index}] source={item.get('source', '')} doc_id={item.get('doc_id', '')}\n{item.get('content', '')}"
                for index, item in enumerate(results, start=1)
            ) or "(no evidence retrieved)"
            try:
                without = chat(
                    base_url,
                    api_key,
                    model,
                    "Answer this finance question briefly. If you are not sure, say you do not know.\n\n" + query,
                    args.timeout,
                )
                with_context = chat(
                    base_url,
                    api_key,
                    model,
                    "Answer using only the evidence. If it is not enough, say you do not know.\n\n"
                    f"Evidence:\n{evidence}\n\nQuestion: {query}",
                    args.timeout,
                )
            except Exception as exc:
                print(f"NOT RUN: LLM call failed: {exc}. Partial scores were discarded.", file=sys.stderr)
                return 2
            gold = str(case.get("gold_answer") or "")
            row["with_retrieval"] = answer_contains_gold(with_context, gold)
            row["without_retrieval"] = answer_contains_gold(without, gold)
            with_gold.append(row["with_retrieval"])
            without_gold.append(row["without_retrieval"])
        rows.append(row)

    report: dict[str, Any] = {
        "status": "measured",
        "dataset": str(args.dataset),
        "samples": len(rows),
        "top_k": args.top_k,
        "rewrite": args.rewrite,
        "evidence_hit_rate": mean(evidence_hits),
        "answer_quality": None,
        "cases": rows,
    }
    if llm is None:
        report["answer_quality_status"] = "not_measured"
        report["answer_quality_reason"] = "DEEPSEEK_API_KEY and OPENAI_API_KEY are unset, so answers were not generated."
    else:
        report["answer_quality_status"] = "measured"
        report["answer_quality"] = {
            "metric": "gold number contained in the answer, years ignored",
            "with_mcp_retrieval": mean(with_gold),
            "without_mcp_retrieval": mean(without_gold),
        }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
