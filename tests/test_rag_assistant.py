from __future__ import annotations

import pytest
from langchain_core.documents import Document

from research_tool.llm.models import GenerationResult, HealthStatus
from research_tool.rag.assistant import AnswerService, ReportService


class FakeIndex:
    def search(self, query: str, top_k: int = 5) -> list[Document]:
        return [
            Document(
                page_content="evidence",
                metadata={"source_url": "https://example.com/evidence"},
            )
        ]


class FakeProvider:
    @property
    def name(self) -> str:
        return "fake"

    async def generate(self, prompt: str, *, instructions: str) -> GenerationResult:
        assert "evidence" in prompt
        return GenerationResult("answer")

    def health_check(self, *, live: bool = False) -> HealthStatus:
        return HealthStatus("fake", True, "ready")

    def describe(self) -> str:
        return "Fake / model"


@pytest.mark.asyncio
async def test_answer_and_report_use_shared_service(tmp_path) -> None:
    answer_service = AnswerService(FakeIndex(), FakeProvider())  # type: ignore[arg-type]

    answer = await answer_service.ask("question")
    report, path = await ReportService(answer_service, tmp_path / "reports").generate("request")

    assert answer.answer == "answer"
    assert answer.sources == ("https://example.com/evidence",)
    assert report.answer == "answer"
    assert path.is_file()
    assert "Fake / model" in path.read_text(encoding="utf-8")
