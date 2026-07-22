from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Protocol

from langchain_core.documents import Document

from research_tool.shared.errors import IndexError


class VectorStore(Protocol):
    def add(self, documents: list[Document], ids: list[str]) -> None: ...

    def delete(self, ids: list[str]) -> None: ...

    def search(self, query: str, top_k: int) -> list[Document]: ...

    def reset(self) -> None: ...

    def ready(self) -> bool: ...


class ChromaVectorStore:
    def __init__(self, index_dir: Path, runtime_root: Path, embedding_model: str) -> None:
        self.index_dir = index_dir.resolve()
        self.runtime_root = runtime_root.resolve()
        self.embedding_model = embedding_model
        self._store: Any | None = None

    def add(self, documents: list[Document], ids: list[str]) -> None:
        if documents:
            self._get_store().add_documents(documents=documents, ids=ids)

    def delete(self, ids: list[str]) -> None:
        if ids and self.ready():
            self._get_store().delete(ids=ids)

    def search(self, query: str, top_k: int) -> list[Document]:
        if not self.ready():
            raise IndexError("RAG 索引尚未建立，请先执行 index update。")
        return list(self._get_store().similarity_search(query, k=top_k))

    def reset(self) -> None:
        if self.index_dir == self.runtime_root or not self.index_dir.is_relative_to(
            self.runtime_root
        ):
            raise IndexError(f"拒绝删除不安全的索引路径：{self.index_dir}")
        self._store = None
        if self.index_dir.exists():
            shutil.rmtree(self.index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def ready(self) -> bool:
        return (self.index_dir / "chroma.sqlite3").is_file()

    def _get_store(self) -> Any:
        if self._store is None:
            from langchain_community.vectorstores import Chroma
            from langchain_huggingface import HuggingFaceEmbeddings

            self.index_dir.mkdir(parents=True, exist_ok=True)
            embeddings = HuggingFaceEmbeddings(model_name=self.embedding_model)
            self._store = Chroma(
                collection_name="research_tool",
                persist_directory=str(self.index_dir),
                embedding_function=embeddings,
            )
        return self._store
