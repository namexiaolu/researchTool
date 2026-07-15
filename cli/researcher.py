from __future__ import annotations

import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"


def _load_grok_env() -> dict[str, str]:
    env = {
        "url": os.getenv("GROK_API_URL", ""),
        "key": os.getenv("GROK_API_KEY", ""),
        "model": os.getenv("GROK_MODEL", ""),
    }
    if env["key"]:
        return env

    config_paths = [
        Path(os.getenv("OPENCODE_CONFIG_PATH", "")),
        Path.home() / ".config" / "opencode" / "opencode.json",
        Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode" / "opencode.json",
    ]
    for cp in config_paths:
        if not cp.is_file():
            continue
        try:
            data = json.loads(cp.read_text(encoding="utf-8"))
            mcp = data.get("mcp") or {}
            gs = mcp.get("grok-search") or {}
            gs_env = gs.get("environment") or {}
            if gs_env.get("GROK_API_KEY"):
                env["key"] = gs_env["GROK_API_KEY"]
                env["url"] = gs_env.get("GROK_API_URL", env["url"])
                env["model"] = gs_env.get("GROK_MODEL", env["model"])
                return env
        except (OSError, json.JSONDecodeError):
            continue

    return env


_grok_env = _load_grok_env()
GROK_API_URL = _grok_env["url"] or "https://freeapi.dgbmc.top/v1"
GROK_API_KEY = _grok_env["key"]
GROK_MODEL = _grok_env["model"] or "grok-chat-fast"
BROWSER_RELAY_URL = os.getenv("BROWSER_RELAY_URL", "http://127.0.0.1:18795")


def _models() -> list[str]:
    resp = httpx.get(f"{GROK_API_URL}/models", headers={"Authorization": f"Bearer {GROK_API_KEY}"}, timeout=10)
    data = resp.json()
    return [m["id"] for m in (data.get("data") or data)]


def _get_client() -> OpenAI:
    return OpenAI(api_key=GROK_API_KEY, base_url=GROK_API_URL)


def web_search(query: str) -> str:
    client = _get_client()
    response = client.chat.completions.create(
        model=GROK_MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是一个网络调研助手。请在网络上搜索并返回详细结果，包含来源链接。信息不足时明确说明。",
            },
            {"role": "user", "content": f"搜索以下内容，返回详细结果（含来源链接）：\n\n{query}"},
        ],
        extra_body={"enable_search": True},
    )
    return response.choices[0].message.content


def web_fetch_httpx(url: str) -> Optional[str]:
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        }
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines[:500])
    except Exception:
        return None


def download_pdf(url: str, topic: str) -> Optional[Path]:
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        }
        resp = httpx.get(url, headers=headers, follow_redirects=True, timeout=90)
        resp.raise_for_status()
        papers_dir = KNOWLEDGE_ROOT / "papers"
        papers_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", topic)[:30] or "未命名"
        filename = f"paper_{safe}_{ts}.pdf"
        filepath = papers_dir / filename
        filepath.write_bytes(resp.content)
        return filepath
    except Exception:
        return None


def fetch_arxiv(url: str) -> Optional[str]:
    try:
        abs_url = re.sub(r'/pdf/(\d+\.\d+)(v\d+)?(\.pdf)?', r'/abs/\1\2', url)
        abs_url = re.sub(r'\.pdf$', '', abs_url)
        if abs_url == url and "/abs/" not in abs_url:
            return web_fetch_httpx(url)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        }
        resp = httpx.get(abs_url, headers=headers, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        title = ""
        title_tag = soup.find("h1", class_="title")
        if title_tag:
            title = title_tag.get_text(strip=True).removeprefix("Title:").strip()

        authors = ""
        authors_tag = soup.find("div", class_="authors")
        if authors_tag:
            authors = authors_tag.get_text(strip=True).removeprefix("Authors:").strip()

        abstract = ""
        abstract_tag = soup.find("blockquote", class_="abstract")
        if abstract_tag:
            abstract = abstract_tag.get_text(strip=True).removeprefix("Abstract:").strip()

        return (
            f"## Title\n\n{title}\n\n"
            f"## Authors\n\n{authors}\n\n"
            f"## URL\n\n{abs_url}\n\n"
            f"## Abstract\n\n{abstract}\n"
        )
    except Exception:
        return web_fetch_httpx(url)


def _br_api_get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    try:
        resp = httpx.get(
            f"{BROWSER_RELAY_URL}{path}",
            params=params or {},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def _br_api_post(path: str, body: dict) -> Optional[dict]:
    try:
        resp = httpx.post(
            f"{BROWSER_RELAY_URL}{path}",
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def web_fetch_browser(url: str) -> Optional[str]:
    tabs_data = _br_api_get("/api/tabs")
    if not tabs_data:
        return None
    tabs = tabs_data.get("tabs") or []
    if not tabs:
        return None
    tab_id = tabs[0]["id"]
    _br_api_post("/api/navigate", {"url": url, "tabId": tab_id})
    time.sleep(2)
    snap = _br_api_get("/api/snapshot", {"tabId": tab_id, "format": "text", "maxLength": 50000})
    if snap:
        return snap.get("content")
    return None


def web_fetch(url: str, use_browser: bool = False) -> Optional[str]:
    if use_browser:
        return web_fetch_browser(url)
    return web_fetch_httpx(url)


def classify_content(url: str, content: str) -> str:
    url_lower = url.lower()
    pre = (content or "")[:1500].lower()

    papers = [
        "arxiv", "scholar.google", "researchgate", "acm.org", "ieee",
        "springer", "doi.org", "pdf", "jstor", "sciencedirect", "mdpi",
        "wiley.com", "tailieu", "semanticscholar", "paper",
    ]
    if any(ind in url_lower for ind in papers) or any(ind in pre for ind in papers):
        return "papers"

    reports = ["report", "whitepaper", "technical.report", "benchmark"]
    if any(re.search(r, url_lower) for r in reports):
        return "reports"

    sources = [
        "github.com", "gitlab", "docs.", "documentation", "api.",
        "manual", "tutorial", "blog.", "news.", "medium.com",
        "dev.to", "stackoverflow", "wiki",
    ]
    if any(ind in url_lower for ind in sources):
        return "sources"

    return "web"


def save_content(category: str, topic: str, content: str, source_url: str = "") -> Path:
    category_dir = KNOWLEDGE_ROOT / category
    category_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", topic)[:30] or "未命名"
    filename = f"{category}_{safe}_{ts}.md"
    filepath = category_dir / filename

    doc = (
        f"# {category.title()} — {topic}\n\n"
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"- 来源：{source_url}\n\n"
        f"## 内容\n\n{content}\n"
    )
    filepath.write_text(doc, encoding="utf-8")
    return filepath


def save_summary(topic: str, report: str) -> Path:
    output_dir = KNOWLEDGE_ROOT / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", topic)[:30] or "未命名"
    filename = f"报告_{safe}_{ts}.md"
    filepath = output_dir / filename

    doc = (
        f"# 调研报告\n\n"
        f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n"
        f"- 主题：{topic}\n\n"
        f"{report}\n"
    )
    filepath.write_text(doc, encoding="utf-8")
    return filepath


ARXIV_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
SEMANTIC_SCHOLAR_FIELDS = "title,authors,year,abstract,openAccessPdf,externalIds,citationCount,venue"


def search_arxiv(topic: str, max_results: int = 5) -> list[dict]:
    for attempt in range(3):
        try:
            resp = httpx.get(
                "http://export.arxiv.org/api/query",
                params={"search_query": f"all:{topic}", "max_results": max_results, "start": 0},
                follow_redirects=True,
                timeout=60,
            )
            if resp.status_code == 429:
                wait = [30, 60, 120][attempt]
                time.sleep(wait)
                continue
            resp.raise_for_status()
        except Exception:
            if attempt < 2:
                time.sleep(3)
                continue
            return []

        if not resp.text.strip():
            if attempt < 2:
                time.sleep(3)
                continue
            return []

    papers = []
    root = ET.fromstring(resp.text)
    for entry in root.findall("a:entry", ARXIV_NS):
        title_el = entry.find("a:title", ARXIV_NS)
        summary_el = entry.find("a:summary", ARXIV_NS)
        id_el = entry.find("a:id", ARXIV_NS)
        updated_el = entry.find("a:updated", ARXIV_NS)

        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
        summary = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""
        arxiv_id = ""
        if id_el is not None and id_el.text:
            arxiv_id = id_el.text.strip().split("/")[-1].split("v")[0]
        year = (updated_el.text or "")[:4] if updated_el is not None else ""

        authors = []
        for author_el in entry.findall("a:author", ARXIV_NS):
            name_el = author_el.find("a:name", ARXIV_NS)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""

        papers.append({
            "title": title,
            "authors": authors,
            "abstract": summary,
            "year": year,
            "pdf_url": pdf_url,
            "source": "arxiv",
            "arxiv_id": arxiv_id,
        })
    return papers


def search_semantic_scholar(topic: str, max_results: int = 5) -> list[dict]:
    papers_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    delays = [3, 10, 30]
    for attempt in range(3):
        try:
            resp = httpx.get(
                papers_url,
                params={"query": topic, "limit": max_results, "fields": SEMANTIC_SCHOLAR_FIELDS},
                timeout=30,
            )
            if resp.status_code == 429:
                wait = delays[attempt]
                time.sleep(wait)
                continue
            resp.raise_for_status()
        except Exception:
            return []

        data = resp.json()
        results = []
        for item in data.get("data") or []:
            oa = item.get("openAccessPdf") or {}
            ext_ids = item.get("externalIds") or {}
            authors = [a.get("name", "") for a in (item.get("authors") or []) if a.get("name")]
            results.append({
                "title": item.get("title", ""),
                "authors": authors,
                "abstract": item.get("abstract", "") or "",
                "year": str(item.get("year") or ""),
                "pdf_url": oa.get("url", ""),
                "source": "semantic_scholar",
                "doi": ext_ids.get("DOI", ""),
                "venue": item.get("venue", ""),
                "citation_count": item.get("citationCount", 0),
            })
        return results
    return []


def search_academic_papers(topic: str, max_results: int = 5) -> list[dict]:
    papers = []
    arxiv_results = search_arxiv(topic, max_results)
    papers.extend(arxiv_results)
    ss_results = search_semantic_scholar(topic, max_results)
    seen_titles = {p["title"] for p in papers}
    for p in ss_results:
        if p["title"] not in seen_titles:
            papers.append(p)
            seen_titles.add(p["title"])
    return papers


def format_paper_markdown(paper: dict) -> str:
    authors = ", ".join(paper.get("authors") or [])
    parts = [
        f"## Title\n\n{paper['title']}\n",
        f"## Authors\n\n{authors}\n",
        f"## Year\n\n{paper.get('year', '')}\n",
        f"## Source\n\n{paper.get('source', '')}\n",
    ]
    doi = paper.get("doi", "")
    if doi:
        parts.append(f"## DOI\n\n{doi}\n")
    venue = paper.get("venue", "")
    if venue:
        parts.append(f"## Venue\n\n{venue}\n")
    citations = paper.get("citation_count", 0)
    if citations:
        parts.append(f"## Citation Count\n\n{citations}\n")
    arxiv_id = paper.get("arxiv_id", "")
    if arxiv_id:
        parts.append(f"## arXiv ID\n\n{arxiv_id}\n")
    pdf_url = paper.get("pdf_url", "")
    if pdf_url:
        parts.append(f"## PDF\n\n{pdf_url}\n")
    abstract = paper.get("abstract", "")
    if abstract:
        parts.append(f"## Abstract\n\n{abstract}\n")
    return "\n".join(parts)


def fetch_and_save_academic_paper(paper: dict, topic: str, output: list[dict]) -> bool:
    content = format_paper_markdown(paper)
    if len(content.strip()) < 100:
        return False

    source_url = paper.get("pdf_url", "") or paper.get("doi", "") or paper.get("arxiv_id", "")
    path = save_content("papers", topic, content, source_url=source_url)
    print(f"            已保存论文元数据：{path.name}")

    pdf_url = paper.get("pdf_url", "")
    if pdf_url:
        pdf_path = download_pdf(pdf_url, topic)
        if pdf_path:
            print(f"            已下载论文 PDF：{pdf_path.name}")
        else:
            print(f"            PDF 下载失败，跳过")

    output.append({"url": source_url, "category": "papers", "path": str(path)})
    return True


def _generate_plan(topic: str) -> list[dict]:
    plan_prompt = (
        f"你是一个调研规划助手。针对以下主题，生成 3-5 个子查询和每条的搜索关键词。\n"
        f"返回 JSON 格式：{{\"sub_queries\": [{{\"id\": \"sq1\", \"query\": \"...\", "
        f"\"goal\": \"...\", \"keywords\": [\"...\"]}}]}}\n\n"
        f"主题：{topic}\n\n"
        f"要求：子查询覆盖中文和英文资料，覆盖基本概念、对比分析、最新进展、"
        f"相关论文/文献（包括 arXiv、SemanticScholar、ResearchGate 等学术平台）。"
    )
    client = _get_client()
    for attempt in range(2):
        try:
            messages = [{"role": "user", "content": plan_prompt}]
            if attempt == 1:
                messages[0]["content"] += "\n\n请一定严格按照 JSON 格式返回，不要包含其他内容。"
            plan_resp = client.chat.completions.create(
                model=GROK_MODEL,
                messages=messages,
            )
            text = plan_resp.choices[0].message.content.strip()
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                plan = json.loads(match.group())
                sub_queries = plan.get("sub_queries") or plan.get("queries") or []
                if sub_queries:
                    return sub_queries
        except Exception:
            continue

    return [
        {"id": "sq1", "query": topic, "goal": f"搜索「{topic}」的基本信息", "keywords": [topic]},
        {"id": "sq2", "query": f"{topic} comparison", "goal": "搜索对比分析", "keywords": [f"{topic} comparison"]},
        {"id": "sq3", "query": f"{topic} latest 2025 2026", "goal": "搜索最新进展", "keywords": [f"{topic} latest"]},
    ]


def conduct_research(topic: str) -> dict:
    started_at = time.perf_counter()
    print(f"\n[过程 1/7] 生成调研计划 — 将「{topic}」拆分为子问题...")

    sub_queries = _generate_plan(topic)
    print(f"        共 {len(sub_queries)} 个子查询")

    all_pages: list[dict] = []

    for sq in sub_queries:
        sq_id = sq.get("id", "?")
        query = sq.get("query", sq.get("keywords", [""])[0])
        print(f"\n[过程 2/7] 执行子查询 [{sq_id}]：{query[:60]}...")

        search_result = web_search(query)
        print(f"        搜索完成，{len(search_result)} 个字符")

        urls = re.findall(r"https?://[^\s\)\]}<>'\"]+", search_result)
        unique_urls = list(dict.fromkeys(urls))[:5]
        print(f"        发现 {len(unique_urls)} 个链接")

        page_saved = False
        for i, url in enumerate(unique_urls, 1):
            print(f"  [过程 3/6] 抓取页面 [{sq_id}/{i}]：{url[:60]}...")
            url_lower = url.lower()

            # PDF 链接 → 直接下载文件
            if url_lower.endswith(".pdf"):
                pdf_path = download_pdf(url, topic)
                if pdf_path:
                    print(f"            已下载论文 PDF：{pdf_path.name}")
                    all_pages.append({"url": url, "category": "papers", "path": str(pdf_path)})
                    page_saved = True
                else:
                    print(f"            下载失败，跳过")
                continue

            use_br = any(
                dom in url_lower
                for dom in [
                    "twitter", "x.com", "facebook", "instagram", "linkedin",
                    "reddit", "weibo", "zhihu",
                ]
            )
            content = web_fetch(url, use_browser=use_br)
            if not content:
                print(f"            抓取失败，跳过")
                continue

            category = classify_content(url, content)

            # arXiv 链接 → 抓取摘要页提升质量
            if "arxiv.org" in url_lower:
                enriched = fetch_arxiv(url)
                if enriched and len(enriched) > 200:
                    content = enriched
                    category = "papers"

            cat_names = {"papers": "论文/文献", "reports": "报告", "sources": "资料/源码", "web": "网页"}
            print(f"            分类：{cat_names.get(category, category)}")

            path = save_content(category, topic, content, source_url=url)
            print(f"            已保存：{path.name}")
            all_pages.append({"url": url, "category": category, "path": str(path)})
            page_saved = True

        if not page_saved:
            print(f"        没有可抓取的页面，保存搜索摘要")
            path = save_content("web", topic, search_result, source_url=f"搜索：{query}")
            print(f"        已保存：{path.name}")
            all_pages.append({"url": query, "category": "web", "path": str(path)})

    print(f"\n[过程 4/7] 学术数据库检索——搜索 arXiv 和 Semantic Scholar...")
    academic_papers = search_academic_papers(topic)
    if academic_papers:
        print(f"        找到 {len(academic_papers)} 篇论文")
        for paper in academic_papers:
            title_short = (paper.get("title") or "")[:60]
            print(f"  [学术] {title_short}...")
            fetch_and_save_academic_paper(paper, topic, all_pages)
    else:
        print(f"        未找到相关论文")

    print(f"\n[过程 5/7] 汇总搜索结果——共 {len(all_pages)} 条内容")
    sources_text = "\n".join(
        f"- [{p['category']}] {p['url']}" for p in all_pages
    )

    summary_prompt = (
        f"以下是关于「{topic}」的调研收集结果。请根据收集到的内容生成一份结构化的中文调研报告。\n\n"
        f"收集的来源：\n{sources_text}\n\n"
        f"报告要求：\n"
        f"1. 包含标题、摘要、主要发现、对比分析、结论\n"
        f"2. 使用 Markdown 格式\n"
        f"3. 每个发现注明来源\n"
        f"4. 信息不足时明确说明，不要编造\n"
        f"5. 如有不同方案请用表格对比"
    )
    print(f"[过程 6/7] 调用 AI 生成综合报告...")
    client = _get_client()
    summary_resp = client.chat.completions.create(
        model=GROK_MODEL,
        messages=[{"role": "user", "content": summary_prompt}],
    )
    report = summary_resp.choices[0].message.content

    report_path = save_summary(topic, report)
    elapsed = time.perf_counter() - started_at
    print(f"[过程 7/7] 报告已保存：{report_path.name}")
    print(f"\n调研完成，耗时 {elapsed:.1f} 秒")

    return {
        "topic": topic,
        "report": report,
        "report_path": str(report_path),
        "pages": all_pages,
        "elapsed": elapsed,
    }
