from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from research_tool.knowledge.models import SourceType


@dataclass(frozen=True)
class CollectedItem:
    document_id: str
    path: Path
    source_url: str
    source_type: SourceType
    created: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "path": str(self.path),
            "source_url": self.source_url,
            "source_type": self.source_type.value,
            "created": self.created,
        }


@dataclass(frozen=True)
class EvidenceFailure:
    source_url: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"source_url": self.source_url, "message": self.message}


@dataclass(frozen=True)
class ResearchResult:
    topic: str
    report_path: Path
    items: tuple[CollectedItem, ...]
    failures: tuple[EvidenceFailure, ...]
    elapsed_seconds: float

    def to_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "report_path": str(self.report_path),
            "items": [item.to_dict() for item in self.items],
            "failures": [failure.to_dict() for failure in self.failures],
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }
