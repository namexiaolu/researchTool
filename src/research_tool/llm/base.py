from __future__ import annotations

from typing import Protocol

from research_tool.llm.models import GenerationResult, HealthStatus


class LlmProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def generate(self, prompt: str, *, instructions: str) -> GenerationResult: ...

    def health_check(self, *, live: bool = False) -> HealthStatus: ...

    def describe(self) -> str: ...
