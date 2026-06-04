import asyncio
from dataclasses import dataclass
from typing import Any


class FaultInjectedError(RuntimeError):
    def __init__(self, component: str, scenario: str) -> None:
        super().__init__(f"{component}:{scenario}")
        self.component = component
        self.scenario = scenario


@dataclass(frozen=True)
class FaultInjector:
    """Opt-in fault injection for load tests and resilience tests."""

    enabled: bool = False
    scenarios: dict[str, str] | None = None

    @classmethod
    def from_settings(
        cls,
        config: Any,
        headers: dict[str, str] | None = None,
    ) -> "FaultInjector":
        header_value = ""
        if headers:
            header_value = headers.get("x-fault-injection", "") or headers.get("X-Fault-Injection", "")
        return cls.from_sources(
            enabled=getattr(config, "fault_injection_enabled", False),
            env_scenarios=getattr(config, "fault_injection_scenarios", ""),
            header_scenarios=header_value,
        )

    @classmethod
    def from_sources(
        cls,
        *,
        enabled: bool,
        env_scenarios: str = "",
        header_scenarios: str = "",
    ) -> "FaultInjector":
        if not enabled:
            return cls(enabled=False, scenarios={})

        scenarios: dict[str, str] = {}
        scenarios.update(_parse_scenarios(env_scenarios))
        scenarios.update(_parse_scenarios(header_scenarios))
        return cls(enabled=True, scenarios=scenarios)

    def scenario_for(self, component: str) -> str | None:
        if not self.enabled or not self.scenarios:
            return None
        return self.scenarios.get(component)

    def maybe_raise(self, component: str) -> None:
        scenario = self.scenario_for(component)
        if scenario in {"down", "timeout", "rate_limit", "error"}:
            raise FaultInjectedError(component, scenario)

    async def maybe_delay(self, component: str) -> None:
        scenario = self.scenario_for(component)
        if scenario == "slow":
            await asyncio.sleep(0.25)


class FaultInjectedLLM:
    def __init__(self, llm: Any, injector: FaultInjector, degradation_policy: Any = None) -> None:
        self.llm = llm
        self.injector = injector
        self.degradation_policy = degradation_policy

    async def chat(self, *args: Any, **kwargs: Any) -> Any:
        self._maybe_raise_llm_fault()
        await self.injector.maybe_delay("llm")
        return await self.llm.chat(*args, **kwargs)

    async def stream_chat(self, *args: Any, **kwargs: Any):
        self._maybe_raise_llm_fault()
        await self.injector.maybe_delay("llm")
        async for token in self.llm.stream_chat(*args, **kwargs):
            yield token

    def _maybe_raise_llm_fault(self) -> None:
        try:
            self.injector.maybe_raise("llm")
        except FaultInjectedError as exc:
            if self.degradation_policy is not None:
                self.degradation_policy.decide(
                    component="llm",
                    failure=exc.scenario,
                )
            raise

    def __getattr__(self, name: str) -> Any:
        return getattr(self.llm, name)


def _parse_scenarios(value: str) -> dict[str, str]:
    scenarios: dict[str, str] = {}
    for item in value.split(","):
        part = item.strip()
        if not part or ":" not in part:
            continue
        component, scenario = part.split(":", 1)
        component = component.strip().lower()
        scenario = scenario.strip().lower()
        if component and scenario:
            scenarios[component] = scenario
    return scenarios
