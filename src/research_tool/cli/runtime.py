from __future__ import annotations

from dataclasses import dataclass

from research_tool.knowledge.repository import KnowledgeRepository
from research_tool.llm.providers import ProviderFactory
from research_tool.rag.index import RagIndexService
from research_tool.rag.store import ChromaVectorStore
from research_tool.shared.events import ProgressCallback
from research_tool.shared.paths import ProjectPaths
from research_tool.shared.settings import AppSettings, SettingsStore


@dataclass(frozen=True)
class Runtime:
    paths: ProjectPaths
    settings_store: SettingsStore
    settings: AppSettings
    knowledge: KnowledgeRepository
    index: RagIndexService
    providers: ProviderFactory

    @classmethod
    def create(cls, progress: ProgressCallback | None = None) -> Runtime:
        paths = ProjectPaths.discover()
        paths.ensure_layout()
        settings_store = SettingsStore(paths.settings)
        settings = settings_store.load()
        knowledge = KnowledgeRepository(paths.knowledge)
        vector_store = ChromaVectorStore(paths.index, paths.runtime, settings.embedding_model)
        index = RagIndexService(
            repository=knowledge,
            vector_store=vector_store,
            manifest_path=paths.state / "index-manifest.json",
            progress=progress,
        )
        return cls(
            paths=paths,
            settings_store=settings_store,
            settings=settings,
            knowledge=knowledge,
            index=index,
            providers=ProviderFactory(settings, paths.root),
        )
