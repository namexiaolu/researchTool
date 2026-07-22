from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class IndexEntry:
    content_hash: str
    chunk_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"content_hash": self.content_hash, "chunk_ids": list(self.chunk_ids)}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> IndexEntry:
        raw_ids = data.get("chunk_ids", [])
        chunk_ids = raw_ids if isinstance(raw_ids, list | tuple) else []
        return cls(
            content_hash=str(data["content_hash"]),
            chunk_ids=tuple(str(item) for item in chunk_ids),
        )


@dataclass
class IndexManifest:
    version: int = 1
    documents: dict[str, IndexEntry] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "documents": {key: value.to_dict() for key, value in self.documents.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> IndexManifest:
        raw_documents = data.get("documents") or {}
        if not isinstance(raw_documents, dict):
            raise ValueError("索引清单 documents 必须是对象。")
        raw_version = data.get("version", 1)
        version = raw_version if isinstance(raw_version, int) else 1
        return cls(
            version=version,
            documents={
                str(key): IndexEntry.from_dict(value)
                for key, value in raw_documents.items()
                if isinstance(value, dict)
            },
        )


@dataclass(frozen=True)
class IndexResult:
    scanned: int
    added: int
    updated: int
    deleted: int
    chunks: int
    rebuilt: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class IndexStatus:
    ready: bool
    document_count: int
    chunk_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    sources: tuple[str, ...]
    provider: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
