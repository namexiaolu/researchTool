from __future__ import annotations

import asyncio
import html
import ipaddress
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import httpx

from research_tool.knowledge.models import SaveResult, SourceType
from research_tool.knowledge.repository import KnowledgeRepository
from research_tool.research.models import CollectedItem, EvidenceFailure
from research_tool.shared.events import ProgressCallback, emit

MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[([^\]]+)\]\((https?://[^\s\)]+)\)")
URL_PATTERN = re.compile(r"https?://[^\s\)\]>]+")
SOURCE_HOSTS = (
    "github.com",
    "gitlab.com",
    "bitbucket.org",
    "gitee.com",
    "codeberg.org",
    "raw.githubusercontent.com",
)
PAPER_HOSTS = (
    "arxiv.org",
    "doi.org",
    "pubmed.ncbi.nlm.nih.gov",
    "dl.acm.org",
    "ieeexplore.ieee.org",
    "link.springer.com",
    "sciencedirect.com",
    "semanticscholar.org",
)
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_CITATIONS = 50
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class Citation:
    url: str
    label: str = ""


@dataclass(frozen=True)
class EvidenceCollection:
    items: tuple[CollectedItem, ...]
    failures: tuple[EvidenceFailure, ...]


@dataclass(frozen=True)
class FetchedResource:
    final_url: str
    content_type: str
    encoding: str
    content: bytes


class EvidenceCollector:
    def __init__(
        self,
        repository: KnowledgeRepository,
        *,
        progress: ProgressCallback | None = None,
        concurrency: int = 4,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.repository = repository
        self.progress = progress
        self.semaphore = asyncio.Semaphore(concurrency)
        self.transport = transport

    async def collect(self, report: str, *, download_papers: bool) -> EvidenceCollection:
        citations = extract_citations(report)[:MAX_CITATIONS]
        if not citations:
            return EvidenceCollection(
                items=(),
                failures=(EvidenceFailure("", "最终报告没有可采集的 HTTP 来源链接。"),),
            )

        emit(
            self.progress,
            "evidence",
            f"开始采集 {len(citations)} 个报告来源",
            source_count=len(citations),
        )
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=self.transport,
            headers={"User-Agent": "ResearchTool/0.1 evidence-collector"},
        ) as client:
            results = await asyncio.gather(
                *(
                    self._limited(client, citation, download_papers=download_papers)
                    for citation in citations
                )
            )

        items: list[CollectedItem] = []
        failures: list[EvidenceFailure] = []
        for result_items, result_failures in results:
            items.extend(result_items)
            failures.extend(result_failures)
        emit(
            self.progress,
            "evidence",
            f"来源采集完成：{len(items)} 份证据，{len(failures)} 个失败项",
            item_count=len(items),
            failure_count=len(failures),
        )
        return EvidenceCollection(tuple(items), tuple(failures))

    async def _limited(
        self,
        client: httpx.AsyncClient,
        citation: Citation,
        *,
        download_papers: bool,
    ) -> tuple[list[CollectedItem], list[EvidenceFailure]]:
        async with self.semaphore:
            return await self._collect_one(
                client,
                citation,
                download_papers=download_papers,
            )

    async def _collect_one(
        self,
        client: httpx.AsyncClient,
        citation: Citation,
        *,
        download_papers: bool,
    ) -> tuple[list[CollectedItem], list[EvidenceFailure]]:
        category = classify_source(citation.url)
        emit(
            self.progress,
            "fetch",
            f"采集来源：{citation.url}",
            source_url=citation.url,
            source_type=category.value,
        )
        try:
            if category is SourceType.PAPERS and _looks_like_pdf(citation.url):
                return await self._collect_direct_pdf(
                    client,
                    citation,
                    download_papers=download_papers,
                )

            resource = await _fetch_resource(client, citation.url, MAX_TEXT_BYTES)
            if _is_pdf(resource):
                return self._save_pdf(citation, resource)

            title, snapshot, pdf_links = _snapshot(resource, citation)
            saved = self.repository.save_text(
                category,
                title,
                snapshot,
                source_url=resource.final_url,
                tags=("evidence", f"{category.value}-snapshot"),
            )
            items = [_collected(saved)]
            failures: list[EvidenceFailure] = []
            if category is SourceType.PAPERS and download_papers and pdf_links:
                try:
                    pdf = await _fetch_resource(client, pdf_links[0], MAX_PDF_BYTES)
                    pdf_items, pdf_failures = self._save_pdf(
                        Citation(pdf.final_url, title),
                        pdf,
                    )
                    items.extend(pdf_items)
                    failures.extend(pdf_failures)
                except Exception as exc:
                    failures.append(EvidenceFailure(pdf_links[0], str(exc)))
            return items, failures
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return [], [EvidenceFailure(citation.url, str(exc))]

    async def _collect_direct_pdf(
        self,
        client: httpx.AsyncClient,
        citation: Citation,
        *,
        download_papers: bool,
    ) -> tuple[list[CollectedItem], list[EvidenceFailure]]:
        if not download_papers:
            metadata = _paper_metadata(citation, local_pdf=None)
            saved = self.repository.save_text(
                SourceType.PAPERS,
                citation.label or _title_from_url(citation.url),
                metadata,
                source_url=citation.url,
                tags=("evidence", "paper-metadata"),
            )
            return [_collected(saved)], []
        resource = await _fetch_resource(client, citation.url, MAX_PDF_BYTES)
        return self._save_pdf(citation, resource)

    def _save_pdf(
        self,
        citation: Citation,
        resource: FetchedResource,
    ) -> tuple[list[CollectedItem], list[EvidenceFailure]]:
        if not _is_pdf(resource):
            return [], [EvidenceFailure(resource.final_url, "来源没有返回 PDF 内容。")]
        title = citation.label or _title_from_url(resource.final_url)
        pdf = self.repository.save_bytes(
            SourceType.PAPERS,
            title,
            resource.content,
            source_url=resource.final_url,
            tags=("evidence", "paper", "pdf"),
            suffix=".pdf",
            media_type="application/pdf",
        )
        metadata = self.repository.save_text(
            SourceType.PAPERS,
            f"{title} 元数据",
            _paper_metadata(citation, local_pdf=pdf),
            source_url=resource.final_url,
            tags=("evidence", "paper-metadata"),
        )
        return [_collected(pdf), _collected(metadata)], []


def extract_citations(report: str) -> tuple[Citation, ...]:
    citations: dict[str, Citation] = {}
    for match in MARKDOWN_LINK_PATTERN.finditer(report):
        label = re.sub(r"[`*_]", "", match.group(1)).strip()
        url = _clean_url(match.group(2))
        citations.setdefault(url, Citation(url, label))
    for match in URL_PATTERN.finditer(report):
        url = _clean_url(match.group(0))
        citations.setdefault(url, Citation(url))
    return tuple(citations.values())


def classify_source(url: str) -> SourceType:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if _host_matches(host, SOURCE_HOSTS):
        return SourceType.SOURCES
    if _looks_like_pdf(url) or _host_matches(host, PAPER_HOSTS):
        return SourceType.PAPERS
    return SourceType.WEB


async def _fetch_resource(
    client: httpx.AsyncClient,
    url: str,
    max_bytes: int,
) -> FetchedResource:
    current = url
    for _ in range(6):
        _validate_public_url(current)
        async with client.stream("GET", current, follow_redirects=False) as response:
            if response.status_code in REDIRECT_CODES:
                location = response.headers.get("location")
                if not location:
                    response.raise_for_status()
                current = urljoin(str(response.url), location)
                continue
            response.raise_for_status()
            raw_length = response.headers.get("content-length", "")
            if raw_length.isdigit() and int(raw_length) > max_bytes:
                raise ValueError(f"来源内容超过限制：{int(raw_length)} 字节")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > max_bytes:
                    raise ValueError(f"来源内容超过限制：{max_bytes} 字节")
            content_type = response.headers.get("content-type", "").lower()
            return FetchedResource(
                final_url=str(response.url),
                content_type=content_type,
                encoding=response.encoding or "utf-8",
                content=bytes(content),
            )
    raise ValueError(f"来源重定向次数过多：{url}")


def _snapshot(resource: FetchedResource, citation: Citation) -> tuple[str, str, list[str]]:
    text = resource.content.decode(resource.encoding, errors="replace")
    collected_at = datetime.now(UTC).isoformat()
    if "html" not in resource.content_type and "<html" not in text[:500].lower():
        title = citation.label or _title_from_url(resource.final_url)
        snapshot = (
            f"# {title}\n\n"
            f"- 来源 URL：{resource.final_url}\n"
            f"- 采集时间：{collected_at}\n"
            f"- 内容类型：{resource.content_type or 'text/plain'}\n\n"
            f"---\n\n{text.strip()}\n"
        )
        return title, snapshot, []

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    pdf_links = [
        urljoin(resource.final_url, str(anchor.get("href")))
        for anchor in soup.find_all("a", href=True)
        if _looks_like_pdf(urljoin(resource.final_url, str(anchor.get("href"))))
    ]
    title = (
        citation.label
        or (soup.title.get_text(" ", strip=True) if soup.title else "")
        or _title_from_url(resource.final_url)
    )
    for element in soup(["script", "style", "noscript", "svg", "template"]):
        element.decompose()
    container = soup.find("article") or soup.find("main") or soup.body or soup
    body = container.get_text("\n", strip=True)
    body = re.sub(r"\n{3,}", "\n\n", body)
    snapshot = (
        f"# {title}\n\n"
        f"- 来源 URL：{resource.final_url}\n"
        f"- 采集时间：{collected_at}\n"
        f"- 内容类型：{resource.content_type or 'text/html'}\n\n"
        f"---\n\n{body}\n"
    )
    return title, snapshot, list(dict.fromkeys(pdf_links))


def _paper_metadata(citation: Citation, local_pdf: SaveResult | None) -> str:
    title = citation.label or _title_from_url(citation.url)
    lines = [
        f"# {title}",
        "",
        f"- 来源 URL：{citation.url}",
        f"- 采集时间：{datetime.now(UTC).isoformat()}",
    ]
    if local_pdf is None:
        lines.append("- 本地 PDF：未下载")
    else:
        lines.extend(
            (
                f"- 本地 PDF：{local_pdf.document.path.name}",
                f"- SHA-256：{local_pdf.document.metadata.content_hash}",
            )
        )
    return "\n".join(lines) + "\n"


def _collected(saved: SaveResult) -> CollectedItem:
    metadata = saved.document.metadata
    return CollectedItem(
        document_id=metadata.document_id,
        path=saved.document.path,
        source_url=metadata.source_url,
        source_type=metadata.source_type,
        created=saved.created,
    )


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"来源 URL 无效：{url}")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        raise ValueError(f"拒绝访问本机来源：{url}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError(f"拒绝访问非公网地址：{url}")


def _is_pdf(resource: FetchedResource) -> bool:
    return "application/pdf" in resource.content_type or resource.content.startswith(b"%PDF")


def _looks_like_pdf(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".pdf") or "/pdf/" in path


def _host_matches(host: str, candidates: tuple[str, ...]) -> bool:
    return any(host == candidate or host.endswith(f".{candidate}") for candidate in candidates)


def _clean_url(url: str) -> str:
    return html.unescape(url).rstrip(".,;:!?\"'")


def _title_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    return name.removesuffix(".pdf") or parsed.hostname or "来源资料"
