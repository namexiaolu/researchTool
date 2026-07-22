from __future__ import annotations

from langchain_core.documents import Document

from research_tool.knowledge.models import KnowledgeDocument, SourceType
from research_tool.knowledge.repository import KnowledgeRepository
from research_tool.rag.index import RagIndexService


class FakeVectorStore:
    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.was_reset = False

    def add(self, documents: list[Document], ids: list[str]) -> None:
        self.documents.update(dict(zip(ids, documents, strict=True)))

    def delete(self, ids: list[str]) -> None:
        for item_id in ids:
            self.documents.pop(item_id, None)

    def search(self, query: str, top_k: int) -> list[Document]:
        return list(self.documents.values())[:top_k]

    def reset(self) -> None:
        self.was_reset = True
        self.documents.clear()

    def ready(self) -> bool:
        return bool(self.documents)


def _loader(document: KnowledgeDocument) -> list[Document]:
    return [
        Document(
            page_content=document.path.read_text(encoding="utf-8"),
            metadata={"source": str(document.path)},
        )
    ]


def test_incremental_index_add_update_delete_and_rebuild(tmp_path) -> None:
    repository = KnowledgeRepository(tmp_path / "knowledge")
    saved = repository.save_text(SourceType.WEB, "document", "first version")
    vector_store = FakeVectorStore()
    service = RagIndexService(
        repository=repository,
        vector_store=vector_store,
        manifest_path=tmp_path / "state" / "manifest.json",
        loader=_loader,
        chunk_size=20,
        chunk_overlap=2,
    )

    first = service.update()
    unchanged = service.update()
    saved.document.path.write_text("second version with more content", encoding="utf-8")
    changed = service.update()
    vector_store.documents.clear()
    recovered = service.update()
    repository.delete(saved.document.metadata.document_id)
    deleted = service.update()
    rebuilt = service.update(rebuild=True)

    assert (first.added, first.updated, first.deleted) == (1, 0, 0)
    assert (unchanged.added, unchanged.updated, unchanged.deleted) == (0, 0, 0)
    assert changed.updated == 1
    assert recovered.rebuilt is True
    assert recovered.added == 1
    assert deleted.deleted == 1
    assert rebuilt.rebuilt is True
    assert vector_store.was_reset is True


def test_status_does_not_initialize_text_splitter(tmp_path) -> None:
    repository = KnowledgeRepository(tmp_path / "knowledge")
    vector_store = FakeVectorStore()

    def fail_if_called(chunk_size: int, chunk_overlap: int):
        raise AssertionError(
            f"状态查询不应创建文本分割器：{chunk_size}/{chunk_overlap}"
        )

    service = RagIndexService(
        repository=repository,
        vector_store=vector_store,
        manifest_path=tmp_path / "state" / "manifest.json",
        splitter_factory=fail_if_called,
    )

    status = service.status()

    assert status.document_count == 0
