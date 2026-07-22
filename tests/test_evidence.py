from __future__ import annotations

import httpx
import pytest

from research_tool.knowledge.models import SourceType
from research_tool.knowledge.repository import KnowledgeRepository
from research_tool.research.evidence import Citation, EvidenceCollector, extract_citations


@pytest.mark.asyncio
async def test_collects_web_source_repository_and_paper_pdf(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://example.com/article":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<html><title>网页证据</title><article>网页原文</article></html>",
            )
        if url == "https://github.com/acme/project":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="<html><title>代码仓库</title><main>README 内容</main></html>",
            )
        if url == "https://arxiv.org/abs/1234.5678":
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=(
                    "<html><title>论文标题</title><article>论文摘要</article>"
                    '<a href="/pdf/1234.5678">PDF</a></html>'
                ),
            )
        if url == "https://arxiv.org/pdf/1234.5678":
            return httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"%PDF-1.7 test paper",
            )
        raise AssertionError(f"unexpected request: {url}")

    repository = KnowledgeRepository(tmp_path / "knowledge")
    collector = EvidenceCollector(repository, transport=httpx.MockTransport(handler))
    report = """
    [网页案例](https://example.com/article)
    [项目源码](https://github.com/acme/project)
    [研究论文](https://arxiv.org/abs/1234.5678)
    """

    result = await collector.collect(report, download_papers=True)

    assert result.failures == ()
    assert len(result.items) == 5
    documents = repository.list_documents()
    assert sum(doc.metadata.source_type is SourceType.WEB for doc in documents) == 1
    assert sum(doc.metadata.source_type is SourceType.SOURCES for doc in documents) == 1
    assert sum(doc.metadata.source_type is SourceType.PAPERS for doc in documents) == 3
    assert any(doc.path.suffix == ".pdf" for doc in documents)
    markdown = [
        doc.path.read_text(encoding="utf-8")
        for doc in documents
        if doc.path.suffix == ".md"
    ]
    assert any("网页原文" in content for content in markdown)
    assert any("README 内容" in content for content in markdown)


@pytest.mark.asyncio
async def test_rejects_private_evidence_urls(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"private URL must not be requested: {request.url}")

    collector = EvidenceCollector(
        KnowledgeRepository(tmp_path / "knowledge"),
        transport=httpx.MockTransport(handler),
    )

    result = await collector.collect("来源：http://127.0.0.1/private", download_papers=True)

    assert result.items == ()
    assert len(result.failures) == 1
    assert "非公网地址" in result.failures[0].message


def test_extract_citations_keeps_markdown_labels_and_deduplicates() -> None:
    citations = extract_citations(
        "[官方报告](https://example.com/report) 和 https://example.com/report"
    )

    assert citations == (Citation("https://example.com/report", "官方报告"),)
