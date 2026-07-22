from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from langchain_core.documents import Document

from research_tool.knowledge.models import KnowledgeDocument
from research_tool.knowledge.repository import KnowledgeRepository
from research_tool.rag.loader import load_document
from research_tool.rag.models import IndexEntry, IndexManifest, IndexResult, IndexStatus
from research_tool.rag.store import VectorStore
from research_tool.shared.errors import IndexError
from research_tool.shared.events import ProgressCallback, emit

DocumentLoader = Callable[[KnowledgeDocument], list[Document]]


class DocumentSplitter(Protocol):
    def split_documents(self, documents: list[Document]) -> list[Document]: ...


SplitterFactory = Callable[[int, int], DocumentSplitter]


def _create_splitter(chunk_size: int, chunk_overlap: int) -> DocumentSplitter:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "；", " ", ""],
    )


class RagIndexService:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        vector_store: VectorStore,
        manifest_path: Path,
        loader: DocumentLoader = load_document,
        progress: ProgressCallback | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        splitter_factory: SplitterFactory = _create_splitter,
    ) -> None:
        self.repository = repository
        self.vector_store = vector_store
        self.manifest_path = manifest_path
        self.loader = loader
        self.progress = progress
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.splitter_factory = splitter_factory
        self._splitter: DocumentSplitter | None = None

    def update(self, *, rebuild: bool = False) -> IndexResult:
        documents = [
            self.repository.refresh(document) for document in self.repository.list_documents()
        ]
        previous = IndexManifest() if rebuild else self._load_manifest()
        if previous.documents and not self.vector_store.ready():
            rebuild = True
            previous = IndexManifest()
        if rebuild:
            emit(self.progress, "index", "重置向量索引")
            self.vector_store.reset()

        current = {doc.metadata.document_id: doc for doc in documents}
        next_entries: dict[str, IndexEntry] = {}
        deleted_ids = sorted(set(previous.documents) - set(current))
        for document_id in deleted_ids:
            self.vector_store.delete(list(previous.documents[document_id].chunk_ids))

        added = 0
        updated = 0
        chunk_count = 0
        for document_id, document in current.items():
            old_entry = previous.documents.get(document_id)
            if old_entry and old_entry.content_hash == document.metadata.content_hash:
                next_entries[document_id] = old_entry
                continue
            emit(self.progress, "index", f"索引：{document.path.name}", document_id=document_id)
            if old_entry:
                self.vector_store.delete(list(old_entry.chunk_ids))
                updated += 1
            else:
                added += 1
            chunks = self._get_splitter().split_documents(self.loader(document))
            chunk_ids = [f"{document_id}:{index}" for index in range(len(chunks))]
            for index, chunk in enumerate(chunks):
                chunk.metadata.update(
                    {
                        "document_id": document_id,
                        "chunk_index": index,
                        "content_hash": document.metadata.content_hash,
                    }
                )
            self.vector_store.add(chunks, chunk_ids)
            chunk_count += len(chunks)
            next_entries[document_id] = IndexEntry(document.metadata.content_hash, tuple(chunk_ids))

        manifest = IndexManifest(documents=next_entries)
        self._save_manifest(manifest)
        emit(self.progress, "index", "索引更新完成", documents=len(documents))
        return IndexResult(
            scanned=len(documents),
            added=added,
            updated=updated,
            deleted=len(deleted_ids),
            chunks=chunk_count,
            rebuilt=rebuild,
        )

    def status(self) -> IndexStatus:
        manifest = self._load_manifest()
        chunks = sum(len(entry.chunk_ids) for entry in manifest.documents.values())
        return IndexStatus(self.vector_store.ready(), len(manifest.documents), chunks)

    def search(self, query: str, top_k: int = 5) -> list[Document]:
        if top_k < 1:
            raise ValueError("top_k 必须大于 0。")
        return self.vector_store.search(query, top_k)

    def _get_splitter(self) -> DocumentSplitter:
        if self._splitter is None:
            self._splitter = self.splitter_factory(self.chunk_size, self.chunk_overlap)
        return self._splitter

    def _load_manifest(self) -> IndexManifest:
        if not self.manifest_path.is_file():
            return IndexManifest()
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("索引清单不是 JSON 对象。")
            return IndexManifest.from_dict(data)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise IndexError(f"无法读取索引清单 {self.manifest_path}：{exc}") from exc

    def _save_manifest(self, manifest: IndexManifest) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_name(f"{self.manifest_path.name}.tmp")
        content = json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n"
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.manifest_path)
