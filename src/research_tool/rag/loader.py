from __future__ import annotations

from langchain_core.documents import Document

from research_tool.knowledge.models import KnowledgeDocument
from research_tool.shared.errors import IndexError


def load_document(document: KnowledgeDocument) -> list[Document]:
    suffix = document.path.suffix.lower()
    metadata = {
        "source": str(document.path),
        "document_id": document.metadata.document_id,
        "source_type": document.metadata.source_type.value,
        "source_url": document.metadata.source_url,
        "title": document.metadata.title,
    }
    if suffix in {".md", ".txt"}:
        content = document.path.read_text(encoding="utf-8", errors="replace")
        return [Document(page_content=content, metadata=metadata)]
    if suffix == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader

        pages = PyPDFLoader(str(document.path)).load()
        for page in pages:
            page.metadata.update(metadata)
        return pages
    raise IndexError(f"不支持的知识文件类型：{document.path}")
