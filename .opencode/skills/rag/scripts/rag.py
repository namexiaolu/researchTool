#!/usr/bin/env python3
"""
rag — 本地知识库 RAG 工具

Usage:
    python scripts/rag.py build                      # 构建/更新索引
    python scripts/rag.py query --query "..."        # 检索
    python scripts/rag.py add-web --url "..."        # 添加网页
    python scripts/rag.py list                       # 列出已索引文档
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────
KNOWLEDGE_DIR = Path(os.environ.get("RAG_KNOWLEDGE_DIR", Path.home() / ".rag-knowledge"))
DOCS_DIR = KNOWLEDGE_DIR / "docs"
WEB_DIR = KNOWLEDGE_DIR / "web"
VECTOR_STORE_DIR = KNOWLEDGE_DIR / "vector_store"
CHUNK_SIZE = 512
CHUNK_OVERLAP = 128
EMBED_MODEL = "all-MiniLM-L6-v2"
COLLECTION_NAME = "knowledge"


# ── 文本分块 ─────────────────────────────────────────────────
def chunk_text(text: str) -> list[dict]:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks = []
    buffer = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buffer) + len(para) < CHUNK_SIZE:
            buffer = (buffer + "\n\n" + para).strip()
        else:
            if buffer:
                chunks.append({"text": buffer, "size": len(buffer)})
                # overlap: take last CHUNK_OVERLAP chars
                overlap_start = max(0, len(buffer) - CHUNK_OVERLAP)
                buffer = buffer[overlap_start:] + "\n\n" + para
            else:
                # para itself exceeds CHUNK_SIZE, hard split
                for i in range(0, len(para), CHUNK_SIZE - CHUNK_OVERLAP):
                    piece = para[i : i + CHUNK_SIZE]
                    chunks.append({"text": piece, "size": len(piece)})
                buffer = ""

    if buffer:
        chunks.append({"text": buffer, "size": len(buffer)})
    return chunks


# ── 文件解析 ─────────────────────────────────────────────────
def parse_file(filepath: Path) -> str | None:
    ext = filepath.suffix.lower()
    try:
        if ext == ".pdf":
            return _parse_pdf(filepath)
        elif ext == ".docx":
            return _parse_docx(filepath)
        elif ext in (".md", ".txt", ".html", ".htm"):
            return filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"    [warn]  {filepath.name}: {e}", file=sys.stderr)
        return None
    return None


def _parse_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


# ── 索引构建 ─────────────────────────────────────────────────
def cmd_build(args):
    _ensure_dirs()
    texts = []
    metadatas = []
    ids = []

    files_found = 0
    for folder, source_type in [(DOCS_DIR, "local"), (WEB_DIR, "web")]:
        if not folder.exists():
            continue
        for fpath in sorted(folder.iterdir()):
            if fpath.suffix.lower() not in (".pdf", ".docx", ".md", ".txt", ".html", ".htm"):
                continue
            files_found += 1
            print(f"    [file] {fpath.relative_to(KNOWLEDGE_DIR)}", file=sys.stderr)
            raw = parse_file(fpath)
            if not raw:
                continue
            chunks = chunk_text(raw)
            for i, ch in enumerate(chunks):
                texts.append(ch["text"])
                metadatas.append({
                    "source": str(fpath.relative_to(KNOWLEDGE_DIR)),
                    "file_type": fpath.suffix.lower(),
                    "chunk_index": i,
                })
                ids.append(f"{fpath.stem}_{source_type}_{i}")

    if not texts:
        print("  [warn]  没有找到可索引的文件", file=sys.stderr)
        return

    from sentence_transformers import SentenceTransformer
    print(f"    [model] 加载嵌入模型 {EMBED_MODEL}...", file=sys.stderr)
    model = SentenceTransformer(EMBED_MODEL)
    print(f"    [embed] 嵌入 {len(texts)} 个文本块...", file=sys.stderr)
    embeddings = model.encode(texts, show_progress_bar=True).tolist()

    import chromadb
    from chromadb.errors import NotFoundError
    client = chromadb.PersistentClient(str(VECTOR_STORE_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME)
        collection.delete(collection.get()["ids"])
        print("    [reuse]  重建已有集合", file=sys.stderr)
    except NotFoundError:
        collection = client.create_collection(COLLECTION_NAME)

    batch_size = 128
    for i in range(0, len(texts), batch_size):
        end = i + batch_size
        collection.add(
            ids=ids[i:end],
            embeddings=embeddings[i:end],
            documents=texts[i:end],
            metadatas=metadatas[i:end],
        )
    print(f"    [done] 索引完成: {len(texts)} 个块来自 {files_found} 个文件", file=sys.stderr)


# ── 查询 ─────────────────────────────────────────────────────
def cmd_query(args):
    if not VECTOR_STORE_DIR.exists():
        print("  [warn]  向量库不存在，请先运行 build", file=sys.stderr)
        return

    import chromadb
    from chromadb.errors import NotFoundError
    client = chromadb.PersistentClient(str(VECTOR_STORE_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except NotFoundError:
        print("  [warn]  集合不存在，请先运行 build", file=sys.stderr)
        return

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(EMBED_MODEL)
    query_emb = model.encode(args.query).tolist()

    results = collection.query(
        query_embeddings=[query_emb],
        n_results=args.top_k,
    )

    output = {
        "query": args.query,
        "results": [],
    }
    for i in range(len(results["ids"][0])):
        output["results"].append({
            "source": results["metadatas"][0][i].get("source", "unknown"),
            "score": round(results["distances"][0][i], 4) if "distances" in results else None,
            "text": results["documents"][0][i],
        })

    print(json.dumps(output, ensure_ascii=False, indent=2))


# ── 添加网页 ────────────────────────────────────────────────
def cmd_add_web(args):
    _ensure_dirs()
    import httpx
    from bs4 import BeautifulSoup

    print(f"  [web] 抓取 {args.url}...", file=sys.stderr)
    try:
        resp = httpx.get(args.url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [err] 抓取失败: {e}", file=sys.stderr)
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.string.strip() if soup.title else "untitled"
    # clean title for filename
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
    # remove main content
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    body = soup.find("body") or soup
    text = body.get_text(separator="\n", strip=True)

    front_matter = f"""---
title: {title}
url: {args.url}
fetched: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}
---

"""
    md_content = front_matter + text
    filepath = WEB_DIR / f"{safe_title}.md"
    filepath.write_text(md_content, encoding="utf-8")
    print(f"  [ok] 已保存: web/{safe_title}.md ({len(text)} chars)", file=sys.stderr)


# ── 列出文档 ─────────────────────────────────────────────────
def cmd_list(args):
    _ensure_dirs()
    if not VECTOR_STORE_DIR.exists():
        print("  [warn]  向量库不存在", file=sys.stderr)
        return

    import chromadb
    from chromadb.errors import NotFoundError
    client = chromadb.PersistentClient(str(VECTOR_STORE_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except NotFoundError:
        print("  [warn]  集合不存在", file=sys.stderr)
        return

    data = collection.get()
    sources = {}
    for meta in data["metadatas"]:
        src = meta.get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1

    print(f"总计 {len(data['ids'])} 个块，{len(sources)} 个文件:\n")
    for src, count in sorted(sources.items()):
        print(f"    [file] {src} ({count} 块)")


# ── 工具函数 ─────────────────────────────────────────────────
def _ensure_dirs():
    for d in [DOCS_DIR, WEB_DIR]:
        d.mkdir(parents=True, exist_ok=True)


# ── CLI ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="rag — 本地知识库 RAG 工具")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="构建/更新索引")
    p_build.set_defaults(func=cmd_build)

    p_query = sub.add_parser("query", help="检索知识库")
    p_query.add_argument("--query", "-q", required=True, help="查询文本")
    p_query.add_argument("--top-k", type=int, default=5, help="返回结果数 (默认 5)")
    p_query.set_defaults(func=cmd_query)

    p_web = sub.add_parser("add-web", help="抓取网页并加入知识库")
    p_web.add_argument("--url", "-u", required=True, help="网页 URL")
    p_web.set_defaults(func=cmd_add_web)

    p_list = sub.add_parser("list", help="列出已索引的文档")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
