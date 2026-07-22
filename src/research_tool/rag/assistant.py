from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path

from research_tool.llm.base import LlmProvider
from research_tool.rag.index import RagIndexService
from research_tool.rag.models import AnswerResult


class AnswerService:
    def __init__(self, index: RagIndexService, provider: LlmProvider) -> None:
        self.index = index
        self.provider = provider

    async def ask(self, question: str, *, top_k: int = 5) -> AnswerResult:
        documents = self.index.search(question, top_k)
        context = "\n\n".join(
            "[来源："
            f"{doc.metadata.get('source_url') or doc.metadata.get('source')}]\n"
            f"{doc.page_content}"
            for doc in documents
        )
        generation = await self.provider.generate(
            f"资料：\n{context}\n\n问题：{question}\n请直接回答问题。",
            instructions="只能根据提供的资料回答；资料不足时明确说明，不要编造。",
        )
        sources = tuple(
            dict.fromkeys(
                str(doc.metadata.get("source_url") or doc.metadata.get("source") or "未知来源")
                for doc in documents
            )
        )
        return AnswerResult(generation.text, sources, self.provider.describe())


class ReportService:
    def __init__(self, answer_service: AnswerService, reports_dir: Path) -> None:
        self.answer_service = answer_service
        self.reports_dir = reports_dir

    async def generate(self, request: str, *, top_k: int = 8) -> tuple[AnswerResult, Path]:
        prompt = (
            f"根据知识库撰写中文 Markdown 调研报告。要求：{request}\n"
            "至少包含标题、摘要、主要发现、对比分析和结论；每项发现注明来源。"
        )
        result = await self.answer_service.ask(prompt, top_k=top_k)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.reports_dir / f"report-{_slug(request)}-{timestamp}.md"
        content = (
            "# 调研报告\n\n"
            f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"- 用户要求：{request}\n"
            f"- AI 后端：{result.provider}\n\n"
            f"{result.answer}\n\n"
            "## 参考来源\n\n" + "\n".join(f"- {source}" for source in result.sources) + "\n"
        )
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
        return result, path


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", normalized).strip("-_")
    return normalized[:60] or "report"
