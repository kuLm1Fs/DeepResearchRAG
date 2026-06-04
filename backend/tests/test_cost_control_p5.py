import pytest


def test_usage_tracker_records_cost_and_dashboard_summary():
    from src.core.cost_control import UsageEvent, UsageTracker

    tracker = UsageTracker()
    tracker.record(
        UsageEvent(
            trace_id="trace-1",
            company_id="company-a",
            user_id="user-a",
            provider="deepseek",
            model="deepseek-chat",
            operation="chat",
            prompt_tokens=1000,
            completion_tokens=500,
            estimated_cost_usd=0.0015,
        )
    )

    summary = tracker.dashboard(company_id="company-a")

    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["tokens"] == 1500
    assert summary["totals"]["estimated_cost_usd"] == pytest.approx(0.0015)
    assert summary["by_model"][0]["model"] == "deepseek-chat"


def test_budget_policy_blocks_before_call_when_prompt_exceeds_budget():
    from src.core.cost_control import BudgetExceeded, BudgetPolicy

    policy = BudgetPolicy(max_tokens_per_request=50, max_cost_usd_per_request=10)

    with pytest.raises(BudgetExceeded) as exc:
        policy.check_before_call(prompt_tokens=60, provider="deepseek", model="deepseek-chat")

    assert exc.value.partial_report["reason"] == "token_budget_exceeded"
    assert exc.value.partial_report["used_tokens"] == 60


def test_budget_policy_can_track_without_blocking():
    from src.core.cost_control import BudgetPolicy

    policy = BudgetPolicy(max_tokens_per_request=1, max_cost_usd_per_request=0.000001, enabled=False)

    policy.check_before_call(prompt_tokens=10_000, provider="deepseek", model="deepseek-chat")


@pytest.mark.asyncio
async def test_budgeted_llm_tracks_chat_usage():
    from src.core.cost_control import BudgetedLLM, BudgetPolicy, UsageTracker

    class FakeLLM:
        async def chat(self, messages):
            return "x" * 80

    tracker = UsageTracker()
    llm = BudgetedLLM(
        FakeLLM(),
        usage_tracker=tracker,
        budget_policy=BudgetPolicy(max_tokens_per_request=1000, max_cost_usd_per_request=10),
        trace_id="trace-1",
        company_id="company-a",
        user_id="user-a",
        provider="deepseek",
        model="deepseek-chat",
    )

    response = await llm.chat([{"role": "user", "content": "hello"}])

    assert response == "x" * 80
    summary = tracker.dashboard(company_id="company-a")
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["tokens"] > 0


@pytest.mark.asyncio
async def test_budgeted_llm_records_preflight_budget_rejection():
    from src.core.cost_control import BudgetedLLM, BudgetExceeded, BudgetPolicy, UsageTracker

    class FakeLLM:
        async def chat(self, messages):
            return "should not be called"

    tracker = UsageTracker()
    llm = BudgetedLLM(
        FakeLLM(),
        usage_tracker=tracker,
        budget_policy=BudgetPolicy(max_tokens_per_request=1, max_cost_usd_per_request=10),
        trace_id="trace-denied",
        company_id="company-a",
        user_id="user-a",
        provider="deepseek",
        model="deepseek-chat",
    )

    with pytest.raises(BudgetExceeded):
        await llm.chat([{"role": "user", "content": "x" * 80}])

    summary = tracker.dashboard(company_id="company-a")
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["partial_reports"] == 1
    assert summary["totals"]["budget_exceeded"] == 1
    assert summary["recent"][0]["operation"] == "chat"
    assert summary["recent"][0]["completion_tokens"] == 0


@pytest.mark.asyncio
async def test_budgeted_llm_raises_partial_report_when_chat_exceeds_after_generation():
    from src.core.cost_control import BudgetedLLM, BudgetExceeded, BudgetPolicy, UsageTracker

    class FakeLLM:
        async def chat(self, messages):
            return "x" * 80

    tracker = UsageTracker()
    llm = BudgetedLLM(
        FakeLLM(),
        usage_tracker=tracker,
        budget_policy=BudgetPolicy(max_tokens_per_request=10, max_cost_usd_per_request=10),
        trace_id="trace-post-generation",
        company_id="company-a",
        user_id="user-a",
        provider="deepseek",
        model="deepseek-chat",
    )

    with pytest.raises(BudgetExceeded) as exc:
        await llm.chat([{"role": "user", "content": "hello"}])

    assert exc.value.partial_report["reason"] == "token_budget_exceeded"
    summary = tracker.dashboard(company_id="company-a")
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["budget_exceeded"] == 1
    assert summary["recent"][0]["completion_tokens"] > 10


@pytest.mark.asyncio
async def test_budgeted_llm_stream_stops_with_partial_report():
    from src.core.cost_control import BudgetedLLM, BudgetPolicy, UsageTracker

    class FakeLLM:
        async def stream_chat(self, messages):
            for chunk in ("alpha " * 20, "beta " * 20, "gamma " * 20):
                yield chunk

    tracker = UsageTracker()
    llm = BudgetedLLM(
        FakeLLM(),
        usage_tracker=tracker,
        budget_policy=BudgetPolicy(max_tokens_per_request=30, max_cost_usd_per_request=10),
        trace_id="trace-stream",
        company_id="company-a",
        user_id="user-a",
        provider="deepseek",
        model="deepseek-chat",
    )

    chunks = [chunk async for chunk in llm.stream_chat([{"role": "user", "content": "hello"}])]

    assert chunks[-1].startswith("\n\n[partial report]")
    assert "token_budget_exceeded" in chunks[-1]
    summary = tracker.dashboard(company_id="company-a")
    assert summary["totals"]["requests"] == 1
    assert summary["totals"]["budget_exceeded"] == 1
    assert summary["recent"][0]["completion_tokens"] >= 30


@pytest.mark.asyncio
async def test_generate_answer_returns_partial_report_when_budget_exceeded():
    from src.agent.nodes import generate_answer
    from src.core.cost_control import BudgetExceeded

    class FakeRuntime:
        def create_llm(self):
            class FakeLLM:
                async def chat(self, messages):
                    raise BudgetExceeded({
                        "reason": "token_budget_exceeded",
                        "used_tokens": 9001,
                        "estimated_cost_usd": 0.42,
                    })

            return FakeLLM()

        def with_answer_cache(self, llm):
            return llm

    result = await generate_answer({
        "query": "risk",
        "runtime": FakeRuntime(),
        "retrieval_results": [{
            "title": "10-K",
            "content": "risk factors",
            "url": "https://example.com",
            "source": "sec",
            "published_at": "2026-01-01",
            "score": 0.9,
        }],
    })

    assert result["answer"].startswith("[partial report]")
    assert "token_budget_exceeded" in result["answer"]


def test_cost_dashboard_endpoint_returns_company_scope(client):
    from unittest.mock import MagicMock

    from src.api.auth import get_current_user
    from src.core.cost_control import UsageEvent, usage_tracker

    usage_tracker.reset()
    usage_tracker.record(
        UsageEvent(
            trace_id="trace-dashboard",
            company_id="company-a",
            user_id="user-a",
            provider="deepseek",
            model="deepseek-chat",
            operation="chat",
            prompt_tokens=10,
            completion_tokens=20,
            estimated_cost_usd=0.00003,
        )
    )
    mock_user = MagicMock()
    mock_user.id = "user-a"
    mock_user.company_id = "company-a"
    client.app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        resp = client.get("/api/cost/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["requests"] == 1
        assert data["totals"]["tokens"] == 30
    finally:
        usage_tracker.reset()
        client.app.dependency_overrides.clear()
