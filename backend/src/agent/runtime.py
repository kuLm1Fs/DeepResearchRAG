from dataclasses import dataclass, field
from typing import Any

from core import settings


@dataclass
class AgentRuntime:
    """Runtime dependencies for agent nodes.

    Keeping provider construction behind this object lets tests and production
    callers inject LLM/retrieval implementations without patching module globals.
    """

    config: Any = field(default_factory=lambda: settings)

    def create_llm(self):
        from llm import create_llm

        return create_llm(
            provider=self.config.llm_provider,
            api_key=getattr(self.config, f"{self.config.llm_provider}_api_key"),
            model=self.config.llm_model,
        )

    def create_retriever(self):
        from retrieval import MultiPathRetriever
        from vectorstore import MilvusStore

        return MultiPathRetriever(MilvusStore())

    def with_answer_cache(self, llm):
        if not self.config.llm_cache:
            return llm

        from llm.cache import CachedLLM

        return CachedLLM(
            llm,
            cache_dir=self.config.llm_cache_dir / self.config.llm_provider,
        )
