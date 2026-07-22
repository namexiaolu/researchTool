from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    message: str
    current: int | None = None
    total: int | None = None
    data: dict[str, object] = field(default_factory=dict)


class ProgressCallback(Protocol):
    def __call__(self, event: ProgressEvent) -> None: ...


def emit(callback: ProgressCallback | None, stage: str, message: str, **data: object) -> None:
    if callback is not None:
        callback(ProgressEvent(stage=stage, message=message, data=data))
