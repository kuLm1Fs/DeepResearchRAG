from dataclasses import dataclass
from typing import Any

from .metrics import MetricsRegistry, metrics_registry


@dataclass(frozen=True)
class DegradationDecision:
    component: str
    reason: str
    action: str
    degraded: bool
    fallback_strategy: str | None = None
    retryable: bool = False
    user_message: str = ""


class DegradationPolicy:
    """Centralized production policy for controlled fallback vs hard failure."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        metrics: MetricsRegistry = metrics_registry,
    ) -> None:
        self.enabled = enabled
        self.metrics = metrics

    @classmethod
    def from_settings(cls, config: Any) -> "DegradationPolicy":
        return cls(enabled=getattr(config, "degradation_enabled", True))

    def decide(
        self,
        *,
        component: str,
        failure: str,
        requested_strategy: str | None = None,
    ) -> DegradationDecision:
        if not self.enabled:
            return DegradationDecision(
                component=component,
                reason=failure,
                action="fail",
                degraded=False,
                retryable=True,
            )

        decision = self._decide(component, failure, requested_strategy)
        if decision.degraded:
            self.metrics.increment(
                "rag_degradation_events_total",
                labels={
                    "component": decision.component,
                    "action": decision.action,
                    "reason": decision.reason,
                },
            )
        return decision

    def _decide(
        self,
        component: str,
        failure: str,
        requested_strategy: str | None,
    ) -> DegradationDecision:
        if component == "graph":
            return DegradationDecision(
                component=component,
                reason=failure,
                action="fallback",
                degraded=True,
                fallback_strategy="vector",
                retryable=True,
                user_message="Graph retrieval unavailable; using vector retrieval.",
            )

        if component == "llm" and failure in {"timeout", "rate_limit"}:
            return DegradationDecision(
                component=component,
                reason=failure,
                action="fallback",
                degraded=True,
                fallback_strategy="evidence_only",
                retryable=True,
                user_message="LLM unavailable; returning retrieved evidence only.",
            )

        if component == "worker":
            return DegradationDecision(
                component=component,
                reason=failure,
                action="queue",
                degraded=True,
                fallback_strategy="async_retry",
                retryable=True,
                user_message="Research worker unavailable; task remains queued for retry.",
            )

        if component == "milvus":
            return DegradationDecision(
                component=component,
                reason=failure,
                action="fail",
                degraded=False,
                retryable=True,
                user_message="Vector retrieval unavailable.",
            )

        return DegradationDecision(
            component=component,
            reason=failure,
            action="fail",
            degraded=False,
            retryable=False,
        )
