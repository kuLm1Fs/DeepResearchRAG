from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from core.metrics import metrics_registry


def approximate_tokens(value: Any) -> int:
    text = _message_text(value)
    return max(1, len(text) // 4) if text else 0


@dataclass(frozen=True)
class UsageEvent:
    trace_id: str
    company_id: str
    user_id: str
    provider: str
    model: str
    operation: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    partial: bool = False
    budget_exceeded: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str = ""
    used_tokens: int = 0
    estimated_cost_usd: float = 0.0


class BudgetExceeded(RuntimeError):
    def __init__(self, partial_report: dict[str, Any]):
        self.partial_report = partial_report
        super().__init__(partial_report["reason"])


class UsageTracker:
    """In-memory usage ledger for request-level cost visibility.

    This is intentionally process-local for phase 5. The interface is small so
    it can later move to Postgres or Redis without changing LLM call sites.
    """

    def __init__(self, max_events: int = 10_000):
        self.max_events = max_events
        self._events: list[UsageEvent] = []
        self._lock = Lock()

    def record(self, event: UsageEvent) -> None:
        with self._lock:
            self._events.append(event)
            if len(self._events) > self.max_events:
                self._events = self._events[-self.max_events:]

        labels = {
            "provider": event.provider,
            "model": event.model,
            "operation": event.operation,
            "partial": str(event.partial).lower(),
        }
        metrics_registry.increment("rag_usage_requests_total", labels=labels)
        metrics_registry.increment("rag_usage_tokens_total", event.total_tokens, labels=labels)
        metrics_registry.increment("rag_usage_cost_usd_total", event.estimated_cost_usd, labels=labels)
        if event.budget_exceeded:
            metrics_registry.increment("rag_budget_exceeded_total", labels=labels)

    def dashboard(self, company_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)

        if company_id:
            events = [event for event in events if event.company_id == company_id]

        totals = {
            "requests": len(events),
            "tokens": sum(event.total_tokens for event in events),
            "prompt_tokens": sum(event.prompt_tokens for event in events),
            "completion_tokens": sum(event.completion_tokens for event in events),
            "estimated_cost_usd": round(sum(event.estimated_cost_usd for event in events), 8),
            "partial_reports": sum(1 for event in events if event.partial),
            "budget_exceeded": sum(1 for event in events if event.budget_exceeded),
        }
        by_model = _group_usage(events, key=lambda event: (event.provider, event.model))
        by_operation = _group_usage(events, key=lambda event: ("", event.operation))
        recent = sorted(events, key=lambda event: event.created_at, reverse=True)[:limit]

        return {
            "totals": totals,
            "by_model": by_model,
            "by_operation": by_operation,
            "recent": [_serialize_event(event) for event in recent],
        }

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class BudgetPolicy:
    def __init__(
        self,
        max_tokens_per_request: int = 8_000,
        max_cost_usd_per_request: float = 0.05,
        prices_per_1k_tokens: dict[tuple[str, str], float] | None = None,
        enabled: bool = True,
    ):
        self.max_tokens_per_request = max_tokens_per_request
        self.max_cost_usd_per_request = max_cost_usd_per_request
        self.enabled = enabled
        self.prices_per_1k_tokens = prices_per_1k_tokens or {
            ("deepseek", "deepseek-chat"): 0.00042,
            ("openai", "gpt-4o-mini"): 0.0006,
            ("qwen", "qwen-turbo"): 0.0003,
        }

    @classmethod
    def from_settings(cls, config: Any) -> BudgetPolicy:
        return cls(
            max_tokens_per_request=getattr(config, "cost_max_tokens_per_request", 8_000),
            max_cost_usd_per_request=getattr(config, "cost_max_usd_per_request", 0.05),
            enabled=getattr(config, "cost_budget_enabled", True),
        )

    def estimate_cost(self, provider: str, model: str, tokens: int) -> float:
        price = self.prices_per_1k_tokens.get((provider, model), 0.0005)
        return tokens / 1000 * price

    def check_before_call(self, prompt_tokens: int, provider: str, model: str) -> None:
        decision = self.evaluate(prompt_tokens, provider=provider, model=model)
        if not decision.allowed:
            raise BudgetExceeded(_partial_report(decision))

    def evaluate(self, used_tokens: int, provider: str, model: str) -> BudgetDecision:
        estimated_cost = self.estimate_cost(provider, model, used_tokens)
        if not self.enabled:
            return BudgetDecision(allowed=True, used_tokens=used_tokens, estimated_cost_usd=estimated_cost)
        if used_tokens > self.max_tokens_per_request:
            return BudgetDecision(
                allowed=False,
                reason="token_budget_exceeded",
                used_tokens=used_tokens,
                estimated_cost_usd=estimated_cost,
            )
        if estimated_cost > self.max_cost_usd_per_request:
            return BudgetDecision(
                allowed=False,
                reason="cost_budget_exceeded",
                used_tokens=used_tokens,
                estimated_cost_usd=estimated_cost,
            )
        return BudgetDecision(allowed=True, used_tokens=used_tokens, estimated_cost_usd=estimated_cost)


class BudgetedLLM:
    def __init__(
        self,
        llm: Any,
        *,
        usage_tracker: UsageTracker,
        budget_policy: BudgetPolicy,
        trace_id: str,
        company_id: str,
        user_id: str,
        provider: str,
        model: str,
    ):
        self.llm = llm
        self.usage_tracker = usage_tracker
        self.budget_policy = budget_policy
        self.trace_id = trace_id
        self.company_id = company_id
        self.user_id = user_id
        self.provider = provider
        self.model = model

    async def chat(self, messages: list[dict], **kwargs) -> str:
        prompt_tokens = approximate_tokens(messages)
        self._raise_if_preflight_denied("chat", prompt_tokens)

        response = await self.llm.chat(messages, **kwargs)
        completion_tokens = approximate_tokens(response)
        total_tokens = prompt_tokens + completion_tokens
        decision = self.budget_policy.evaluate(total_tokens, self.provider, self.model)
        self._record(
            "chat",
            prompt_tokens,
            completion_tokens,
            partial=not decision.allowed,
            budget_exceeded=not decision.allowed,
        )
        if not decision.allowed:
            raise BudgetExceeded(_partial_report(decision))
        return response

    async def stream_chat(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        prompt_tokens = approximate_tokens(messages)
        self._raise_if_preflight_denied("stream_chat", prompt_tokens)

        completion_tokens = 0
        partial = False
        budget_exceeded = False
        async for chunk in self.llm.stream_chat(messages, **kwargs):
            chunk_tokens = approximate_tokens(chunk)
            decision = self.budget_policy.evaluate(
                prompt_tokens + completion_tokens + chunk_tokens,
                self.provider,
                self.model,
            )
            if not decision.allowed:
                completion_tokens += chunk_tokens
                partial = True
                budget_exceeded = True
                yield "\n\n[partial report] " + _partial_report_text(_partial_report(decision))
                break
            completion_tokens += chunk_tokens
            yield chunk

        self._record(
            "stream_chat",
            prompt_tokens,
            completion_tokens,
            partial=partial,
            budget_exceeded=budget_exceeded,
        )

    def _raise_if_preflight_denied(self, operation: str, prompt_tokens: int) -> None:
        decision = self.budget_policy.evaluate(prompt_tokens, self.provider, self.model)
        if decision.allowed:
            return
        self._record(
            operation,
            prompt_tokens,
            0,
            partial=True,
            budget_exceeded=True,
        )
        raise BudgetExceeded(_partial_report(decision))

    def _record(
        self,
        operation: str,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        partial: bool,
        budget_exceeded: bool,
    ) -> None:
        total_tokens = prompt_tokens + completion_tokens
        self.usage_tracker.record(
            UsageEvent(
                trace_id=self.trace_id,
                company_id=self.company_id,
                user_id=self.user_id,
                provider=self.provider,
                model=self.model,
                operation=operation,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_cost_usd=self.budget_policy.estimate_cost(
                    self.provider,
                    self.model,
                    total_tokens,
                ),
                partial=partial,
                budget_exceeded=budget_exceeded,
            )
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self.llm, name)


usage_tracker = UsageTracker()


def _message_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_message_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(str(value.get(key, "")) for key in ("role", "content"))
    return str(value or "")


def _group_usage(events: list[UsageEvent], key) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        provider, name = key(event)
        item = grouped.setdefault(
            (provider, name),
            {
                "provider": provider,
                "model": name if provider else "",
                "operation": name if not provider else "",
                "requests": 0,
                "tokens": 0,
                "estimated_cost_usd": 0.0,
            },
        )
        item["requests"] += 1
        item["tokens"] += event.total_tokens
        item["estimated_cost_usd"] += event.estimated_cost_usd

    return sorted(
        (
            {**item, "estimated_cost_usd": round(item["estimated_cost_usd"], 8)}
            for item in grouped.values()
        ),
        key=lambda item: item["estimated_cost_usd"],
        reverse=True,
    )


def _serialize_event(event: UsageEvent) -> dict[str, Any]:
    data = asdict(event)
    data["created_at"] = event.created_at.isoformat()
    data["total_tokens"] = event.total_tokens
    data["estimated_cost_usd"] = round(event.estimated_cost_usd, 8)
    return data


def _partial_report(decision: BudgetDecision) -> dict[str, Any]:
    return {
        "reason": decision.reason,
        "used_tokens": decision.used_tokens,
        "estimated_cost_usd": round(decision.estimated_cost_usd, 8),
        "message": "Budget limit reached; returning the evidence gathered so far.",
    }


def _partial_report_text(report: dict[str, Any]) -> str:
    return (
        f"{report['message']} "
        f"reason={report['reason']}; used_tokens={report['used_tokens']}; "
        f"estimated_cost_usd={report['estimated_cost_usd']}"
    )


sys.modules.setdefault("core.cost_control", sys.modules[__name__])
sys.modules.setdefault("src.core.cost_control", sys.modules[__name__])
