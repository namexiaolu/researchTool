from __future__ import annotations

import json

from research_tool.knowledge.models import SourceType
from research_tool.knowledge.repository import KnowledgeRepository


def test_save_deduplicate_refresh_and_delete(tmp_path) -> None:
    repository = KnowledgeRepository(tmp_path / "knowledge")

    first = repository.save_text(
        SourceType.WEB,
        "测试资料",
        "first content",
        source_url="https://example.com",
        tags=("test",),
    )
    duplicate = repository.save_text(SourceType.WEB, "重复资料", "first content")

    assert first.created is True
    assert duplicate.created is False
    assert duplicate.document.metadata.document_id == first.document.metadata.document_id
    assert first.document.path.name.startswith("测试资料--")
    metadata = json.loads(first.document.metadata_path.read_text(encoding="utf-8"))
    assert metadata["source_type"] == "web"
    assert metadata["file_name"] == first.document.path.name

    first.document.path.write_text("changed content", encoding="utf-8")
    refreshed = repository.refresh(first.document)
    assert refreshed.metadata.content_hash != first.document.metadata.content_hash
    assert repository.delete(refreshed.metadata.document_id) is True
    assert repository.list_documents() == []


def test_rejects_empty_content(tmp_path) -> None:
    repository = KnowledgeRepository(tmp_path / "knowledge")

    try:
        repository.save_bytes(SourceType.PAPERS, "empty", b"", suffix=".pdf")
    except Exception as exc:
        assert "空知识文件" in str(exc)
    else:
        raise AssertionError("empty content should fail")
