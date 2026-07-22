from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LlmConfig:
    profile: str
    protocol: str
    model: str
    display_name: str
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    auth_mode: str = "api-key"
    store: bool = False


@dataclass(frozen=True)
class GenerationResult:
    text: str
    reasoning_summaries: tuple[str, ...] = ()


@dataclass(frozen=True)
class HealthStatus:
    provider: str
    ready: bool
    message: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
