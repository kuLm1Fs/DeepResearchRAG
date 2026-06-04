import json
from pathlib import Path

import pytest


def test_graph_failure_policy_falls_back_to_vector_and_records_metrics():
    from src.core.degradation import DegradationPolicy
    from src.core.metrics import MetricsRegistry

    registry = MetricsRegistry()
    policy = DegradationPolicy(metrics=registry)

    decision = policy.decide(
        component="graph",
        failure="timeout",
        requested_strategy="hybrid",
    )

    assert decision.degraded is True
    assert decision.action == "fallback"
    assert decision.fallback_strategy == "vector"
    assert decision.user_message == "Graph retrieval unavailable; using vector retrieval."
    assert 'rag_degradation_events_total{action="fallback",component="graph",reason="timeout"} 1' in (
        registry.render_prometheus()
    )


def test_critical_milvus_failure_is_not_silently_downgraded():
    from src.core.degradation import DegradationPolicy

    decision = DegradationPolicy().decide(
        component="milvus",
        failure="down",
        requested_strategy="hybrid",
    )

    assert decision.degraded is False
    assert decision.action == "fail"
    assert decision.retryable is True


def test_fault_injector_only_honors_headers_when_enabled():
    from src.core.fault_injection import FaultInjectedError, FaultInjector

    disabled = FaultInjector.from_sources(
        enabled=False,
        env_scenarios="graph:timeout",
        header_scenarios="milvus:down",
    )
    disabled.maybe_raise("graph")
    disabled.maybe_raise("milvus")

    enabled = FaultInjector.from_sources(
        enabled=True,
        env_scenarios="graph:timeout",
        header_scenarios="milvus:down",
    )

    with pytest.raises(FaultInjectedError, match="graph:timeout"):
        enabled.maybe_raise("graph")
    with pytest.raises(FaultInjectedError, match="milvus:down"):
        enabled.maybe_raise("milvus")


def test_capacity_report_identifies_error_rate_and_latency_bottlenecks(tmp_path: Path):
    from scripts.generate_capacity_report import build_capacity_report

    locust_summary = {
        "stats": [
            {
                "name": "/api/query",
                "num_requests": 200,
                "num_failures": 8,
                "avg_response_time": 820,
                "median_response_time": 610,
                "current_rps": 12.5,
                "response_time_percentile_0.95": 2100,
                "response_time_percentile_0.99": 4300,
            }
        ]
    }
    summary_path = tmp_path / "locust-summary.json"
    summary_path.write_text(json.dumps(locust_summary), encoding="utf-8")

    report = build_capacity_report(
        summary_path,
        latency_budget_ms=1500,
        error_rate_budget=0.01,
    )

    assert report["routes"][0]["error_rate"] == 0.04
    assert report["routes"][0]["p95_ms"] == 2100
    assert "latency_p95_over_budget" in report["routes"][0]["bottlenecks"]
    assert "error_rate_over_budget" in report["routes"][0]["bottlenecks"]
    assert report["overall_status"] == "needs_capacity_work"


@pytest.mark.asyncio
async def test_retriever_records_graph_degradation_when_fault_is_injected():
    import src.retrieval.retriever as retriever_module
    from src.core.degradation import DegradationPolicy
    from src.core.fault_injection import FaultInjector
    from src.core.metrics import MetricsRegistry
    from src.retrieval.retriever import MultiPathRetriever

    registry = MetricsRegistry()

    class FakeStore:
        async def search_async(self, **kwargs):
            return [{"title": "vector", "content": "vector evidence", "score": 0.9}]

        async def query_async(self, **kwargs):
            return []

    class FakeGraphRetriever:
        async def retrieve(self, query, top_k):
            raise AssertionError("fault injection should stop graph call before network access")

    async def fake_embed(texts):
        return [[0.1] * 1024 for _ in texts]

    original_embed = retriever_module.embed_texts_async
    retriever_module.embed_texts_async = fake_embed
    try:
        retriever = MultiPathRetriever(
            FakeStore(),
            graph_retriever=FakeGraphRetriever(),
            rerank_enabled=False,
            fault_injector=FaultInjector.from_sources(
                enabled=True,
                header_scenarios="graph:timeout",
            ),
            degradation_policy=DegradationPolicy(metrics=registry),
        )

        results = await retriever.retrieve("Apple revenue", top_k=1, strategy="hybrid")
    finally:
        retriever_module.embed_texts_async = original_embed

    assert results[0]["title"] == "vector"
    assert 'rag_degradation_events_total{action="fallback",component="graph",reason="timeout"} 1' in (
        registry.render_prometheus()
    )


def test_agent_runtime_passes_fault_injection_to_retriever(monkeypatch):
    from src.agent.runtime import AgentRuntime
    from src.core.fault_injection import FaultInjector

    captured = {}

    class FakeConfig:
        llm_provider = "deepseek"
        llm_model = "test"
        deepseek_api_key = "key"
        graph_enabled = False
        degradation_enabled = True

    class FakeRetriever:
        def __init__(self, store, graph_retriever=None, fault_injector=None, degradation_policy=None):
            captured["fault_injector"] = fault_injector
            captured["degradation_policy"] = degradation_policy

    monkeypatch.setattr("vectorstore.MilvusStore", lambda: object())
    monkeypatch.setattr("retrieval.MultiPathRetriever", FakeRetriever)

    runtime = AgentRuntime(
        config=FakeConfig(),
        fault_injector=FaultInjector.from_sources(enabled=True, header_scenarios="llm:timeout"),
    )
    runtime.create_retriever()

    assert captured["fault_injector"].scenario_for("llm") == "timeout"
    assert captured["degradation_policy"].enabled is True


@pytest.mark.asyncio
async def test_fault_injected_llm_records_degradation_before_raising():
    from src.core.degradation import DegradationPolicy
    from src.core.fault_injection import FaultInjectedError, FaultInjectedLLM, FaultInjector
    from src.core.metrics import MetricsRegistry

    class FakeLLM:
        async def chat(self, messages):
            return "should not be called"

    registry = MetricsRegistry()
    llm = FaultInjectedLLM(
        FakeLLM(),
        FaultInjector.from_sources(enabled=True, header_scenarios="llm:timeout"),
        DegradationPolicy(metrics=registry),
    )

    with pytest.raises(FaultInjectedError):
        await llm.chat([{"role": "user", "content": "hi"}])

    assert 'rag_degradation_events_total{action="fallback",component="llm",reason="timeout"} 1' in (
        registry.render_prometheus()
    )
