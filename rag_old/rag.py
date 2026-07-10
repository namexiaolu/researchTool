#!/usr/bin/env python3
"""
rag — 本地知识库 RAG 问答系统

索引本地文档 → 语义检索 → 调用 LLM API 生成回答

Usage:
    python rag.py build                            # 构建/更新索引
    python rag.py ask "你的问题"                   # 基于知识库问答
    python rag.py add-web --url "https://..."      # 添加网页到知识库
    python rag.py list                             # 列出已索引文档
    python rag.py configure                        # 查看/修改配置
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ── 路径与默认配置 ────────────────────────────────────────────
KNOWLEDGE_DIR = Path(os.environ.get("RAG_KNOWLEDGE_DIR", Path.home() / ".rag-knowledge"))
DOCS_DIR = KNOWLEDGE_DIR / "docs"
WEB_DIR = KNOWLEDGE_DIR / "web"
VECTOR_STORE_DIR = KNOWLEDGE_DIR / "vector_store"
CONFIG_PATH = KNOWLEDGE_DIR / "config.json"

DEFAULT_CONFIG = {
    "embed_model": "all-MiniLM-L6-v2",
    "chunk_size": 512,
    "chunk_overlap": 128,
    "top_k": 5,
    "language": "zh",
    "generator": "ollama",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "qwen3:0.6b",
    "openai_base_url": "",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
}

COLLECTION_NAME = "knowledge"


# ── 配置管理 ─────────────────────────────────────────────────
def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text("utf-8")))
        except Exception:
            pass
    return config


def save_config(config: dict):
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), "utf-8")


# ── 文本分块 ─────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[dict]:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks, buffer = [], ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buffer) + len(para) < chunk_size:
            buffer = (buffer + "\n\n" + para).strip()
        else:
            if buffer:
                chunks.append(buffer)
                overlap_start = max(0, len(buffer) - chunk_overlap)
                buffer = buffer[overlap_start:] + "\n\n" + para
            else:
                for i in range(0, len(para), chunk_size - chunk_overlap):
                    chunks.append(para[i: i + chunk_size])
                buffer = ""
    if buffer:
        chunks.append(buffer)
    return chunks


# ── 文件解析 ─────────────────────────────────────────────────
def parse_file(filepath: Path) -> str | None:
    ext = filepath.suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(filepath))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        elif ext == ".docx":
            from docx import Document
            doc = Document(str(filepath))
            return "\n".join(p.text for p in doc.paragraphs)
        elif ext in (".md", ".txt", ".html", ".htm"):
            return filepath.read_text("utf-8", errors="replace")
    except Exception as e:
        print(f"  [warn] {filepath.name}: {e}", file=sys.stderr)
    return None


# ── 索引构建 ─────────────────────────────────────────────────
def cmd_build(args):
    config = load_config()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)

    texts, metadatas, ids = [], [], []
    files_found = 0

    for folder, source_type in [(DOCS_DIR, "local"), (WEB_DIR, "web")]:
        if not folder.exists():
            continue
        for fpath in sorted(folder.iterdir()):
            if fpath.suffix.lower() not in (".pdf", ".docx", ".md", ".txt", ".html", ".htm"):
                continue
            files_found += 1
            print(f"  [file] {fpath.relative_to(KNOWLEDGE_DIR)}", file=sys.stderr)
            raw = parse_file(fpath)
            if not raw:
                continue
            for i, ch in enumerate(chunk_text(raw, config["chunk_size"], config["chunk_overlap"])):
                texts.append(ch)
                metadatas.append({"source": str(fpath.relative_to(KNOWLEDGE_DIR)),
                                  "file_type": fpath.suffix.lower(), "chunk_index": i})
                ids.append(f"{fpath.stem}_{source_type}_{i}")

    if not texts:
        print("  [warn] 没有找到可索引的文件", file=sys.stderr)
        return

    from sentence_transformers import SentenceTransformer
    print(f"  [model] 加载嵌入模型 {config['embed_model']}...", file=sys.stderr)
    model = SentenceTransformer(config["embed_model"])
    print(f"  [embed] 嵌入 {len(texts)} 个文本块...", file=sys.stderr)
    embeddings = model.encode(texts, show_progress_bar=True).tolist()

    import chromadb
    from chromadb.errors import NotFoundError
    client = chromadb.PersistentClient(str(VECTOR_STORE_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME)
        collection.delete(collection.get()["ids"])
        print("  [reuse] 重建已有集合", file=sys.stderr)
    except NotFoundError:
        collection = client.create_collection(COLLECTION_NAME)

    for i in range(0, len(texts), 128):
        end = i + 128
        collection.add(ids=ids[i:end], embeddings=embeddings[i:end],
                       documents=texts[i:end], metadatas=metadatas[i:end])

    print(f"  [done] 索引完成: {len(texts)} 个块, {files_found} 个文件", file=sys.stderr)


# ── 检索 ─────────────────────────────────────────────────────
def retrieve(query: str, config: dict) -> list[dict]:
    import chromadb
    from chromadb.errors import NotFoundError
    client = chromadb.PersistentClient(str(VECTOR_STORE_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except NotFoundError:
        return []

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(config["embed_model"])
    query_emb = model.encode(query).tolist()

    results = collection.query(query_embeddings=[query_emb], n_results=config["top_k"])
    items = []
    for i in range(len(results["ids"][0])):
        items.append({
            "source": results["metadatas"][0][i].get("source", "unknown"),
            "score": round(results["distances"][0][i], 4) if "distances" in results else 0,
            "text": results["documents"][0][i],
        })
    return items


# ── 生成（API 调用）──────────────────────────────────────────
def generate(chunks: list[dict], query: str, config: dict) -> str:
    context = "\n\n---\n\n".join(f"[来源: {c['source']}]\n{c['text']}" for c in chunks)
    lang = config.get("language", "zh")
    system = ("你是一个知识库助手。请基于以下上下文内容回答问题。如果上下文不足以回答问题，请如实说不知道。不要编造信息。"
              if lang == "zh" else
              "You are a knowledge base assistant. Answer based on the context below. Say you don't know if the context is insufficient.")
    user = f"上下文：\n{context}\n\n问题：{query}\n\n请基于以上上下文回答问题：" if lang == "zh" else f"Context:\n{context}\n\nQuestion: {query}\n\nAnswer based on the context above:"

    generator = config.get("generator", "ollama")
    if generator == "ollama":
        return _call_ollama(system, user, config)
    elif generator == "openai":
        return _call_openai(system, user, config)
    else:
        return f"[error] 不支持的生成器: {generator}"


def _call_ollama(system: str, prompt: str, config: dict) -> str:
    import httpx
    model = config.get("ollama_model", "qwen3:0.6b")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "stream": False,
    }
    print(f"  [gen] 调用 Ollama ({model})...", file=sys.stderr)
    try:
        resp = httpx.post(f"{config['ollama_url']}/api/chat", json=payload, timeout=120)
        if resp.status_code == 404:
            err = resp.json().get("error", "")
            if "not found" in err:
                print(f"  [err] 模型 '{model}' 不存在", file=sys.stderr)
                print(f"  [hint] 运行 `ollama pull {model}` 下载模型", file=sys.stderr)
                print(f"  [hint] 或运行 `python rag.py configure` 修改 ollama_model", file=sys.stderr)
                print(f"  [hint] 查看已有模型: `ollama list`", file=sys.stderr)
                sys.exit(1)
        resp.raise_for_status()
        return resp.json()["message"]["content"]
    except httpx.ConnectError:
        print(f"  [err] 无法连接 Ollama ({config['ollama_url']})", file=sys.stderr)
        print(f"  [hint] 请确保 Ollama 已安装并启动: https://ollama.com", file=sys.stderr)
        print(f"  [hint] 或运行 `python rag.py configure --set generator openai` 改用 OpenAI 兼容 API", file=sys.stderr)
        sys.exit(1)


def _call_openai(system: str, prompt: str, config: dict) -> str:
    import httpx
    if not config.get("openai_base_url"):
        print("  [err] 未配置 OpenAI 兼容 API", file=sys.stderr)
        print("  [hint] 运行 `python rag.py configure` 设置 openai_base_url 和 openai_api_key", file=sys.stderr)
        sys.exit(1)
    headers = {"Authorization": f"Bearer {config['openai_api_key']}", "Content-Type": "application/json"}
    payload = {
        "model": config.get("openai_model", "gpt-4o-mini"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    print(f"  [gen] 调用 OpenAI 兼容 API ({config['openai_base_url']})...", file=sys.stderr)
    try:
        resp = httpx.post(f"{config['openai_base_url']}/chat/completions", json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except httpx.ConnectError:
        print(f"  [err] 无法连接 API ({config['openai_base_url']})", file=sys.stderr)
        sys.exit(1)


# ── CLI 命令 ─────────────────────────────────────────────────
def cmd_ask(args):
    config = load_config()
    if not VECTOR_STORE_DIR.exists():
        print("[warn] 向量库不存在，请先运行: python rag.py build", file=sys.stderr)
        sys.exit(1)

    print(f"[query] {args.query}", file=sys.stderr)
    print("[retrieve] 检索中...", file=sys.stderr)
    chunks = retrieve(args.query, config)
    if not chunks:
        print("[warn] 未找到相关内容", file=sys.stderr)
        return

    print(f"[retrieve] 找到 {len(chunks)} 个相关片段", file=sys.stderr)
    answer = generate(chunks, args.query, config)

    print("\n" + "=" * 60)
    print(answer)
    print("=" * 60)
    if args.verbose:
        print("\n--- 参考来源 ---")
        for i, c in enumerate(chunks, 1):
            print(f"  {i}. [{c['score']}] {c['source']}")
            print(f"     {c['text'][:150]}...")


def cmd_query(args):
    config = load_config()
    if not VECTOR_STORE_DIR.exists():
        print("[warn] 向量库不存在，请先运行 build", file=sys.stderr)
        return
    chunks = retrieve(args.query, config)
    print(json.dumps({"query": args.query, "results": chunks}, ensure_ascii=False, indent=2))


def cmd_add_web(args):
    import httpx
    from bs4 import BeautifulSoup
    from datetime import datetime

    WEB_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  [web] 抓取 {args.url}...", file=sys.stderr)
    try:
        resp = httpx.get(args.url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [err] 抓取失败: {e}", file=sys.stderr)
        return

    soup = BeautifulSoup(resp.text, "html.parser")
    title = soup.title.string.strip() if soup.title else "untitled"
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:80]
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = (soup.find("body") or soup).get_text(separator="\n", strip=True)

    filepath = WEB_DIR / f"{safe_title}.md"
    filepath.write_text(f"""---
title: {title}
url: {args.url}
fetched: {datetime.now().strftime('%Y-%m-%d %H:%M')}
---

{text}""", "utf-8")
    print(f"  [ok] 已保存: {filepath.relative_to(KNOWLEDGE_DIR)} ({len(text)} chars)", file=sys.stderr)
    print("  运行 python rag.py build 索引后即可查询")


def cmd_list(args):
    if not VECTOR_STORE_DIR.exists():
        print("  [warn] 向量库不存在", file=sys.stderr)
        return
    import chromadb
    from chromadb.errors import NotFoundError
    client = chromadb.PersistentClient(str(VECTOR_STORE_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except NotFoundError:
        print("  [warn] 集合不存在", file=sys.stderr)
        return
    data = collection.get()
    sources = {}
    for m in data["metadatas"]:
        s = m.get("source", "unknown")
        sources[s] = sources.get(s, 0) + 1
    print(f"总计 {len(data['ids'])} 个块, {len(sources)} 个文件:\n")
    for src, cnt in sorted(sources.items()):
        print(f"  [file] {src} ({cnt} 块)")


def cmd_pull(args):
    """通过 Ollama 下载模型"""
    import httpx
    model = args.model
    print(f"  [pull] 下载模型 {model}...", file=sys.stderr)
    print(f"  [hint] 这可能需要几分钟，取决于模型大小和网络速度", file=sys.stderr)
    try:
        with httpx.stream("POST", f"http://localhost:11434/api/pull",
                          json={"name": model, "stream": True}, timeout=600) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    if "status" in data:
                        print(f"    {data['status']}", file=sys.stderr)
                    if data.get("completed"):
                        print(f"  [done] 模型 {model} 下载完成", file=sys.stderr)
                        # 自动设为当前模型
                        config = load_config()
                        config["ollama_model"] = model
                        save_config(config)
                        print(f"  [ok] 已设为默认模型", file=sys.stderr)
    except httpx.ConnectError:
        print("  [err] 无法连接 Ollama", file=sys.stderr)
        sys.exit(1)


def cmd_configure(args):
    config = load_config()
    if args.show:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return
    if args.set:
        key, value = args.set, args.value
        if key in DEFAULT_CONFIG:
            orig = type(DEFAULT_CONFIG[key])
            config[key] = int(value) if orig == int else value
            save_config(config)
            print(f"  [ok] 已设置 {key} = {config[key]}")
        else:
            print(f"  [err] 未知配置项: {key}")
        return
    # 交互模式
    print("当前配置 (直接回车保持不变):\n")
    for key in DEFAULT_CONFIG:
        cur = config.get(key, "")
        inp = input(f"  {key} [{cur}]: ").strip()
        if inp:
            config[key] = int(inp) if isinstance(DEFAULT_CONFIG[key], int) else inp
    save_config(config)
    print("\n  [ok] 配置已保存")


# ── 入口 ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="rag — 本地知识库 RAG 问答系统")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="构建/更新索引")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("ask", help="基于知识库回答问题")
    p.add_argument("query", nargs="?", help="问题")
    p.add_argument("-v", "--verbose", action="store_true", help="显示参考来源")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("query", help="仅检索 (输出 JSON)")
    p.add_argument("-q", "--query", required=True)
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("add-web", help="抓取网页并加入知识库")
    p.add_argument("-u", "--url", required=True)
    p.set_defaults(func=cmd_add_web)

    p = sub.add_parser("list", help="列出已索引文档")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("pull", help="通过 Ollama 下载模型")
    p.add_argument("model", help="模型名 (如 qwen3:0.6b, llama3.2:3b)")
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser("configure", help="查看/修改配置")
    p.add_argument("--show", action="store_true", help="显示当前配置")
    p.add_argument("--set", metavar="KEY")
    p.add_argument("--value", metavar="VAL")
    p.set_defaults(func=cmd_configure)

    args = parser.parse_args()

    if hasattr(args, "query") and args.func == cmd_ask and not args.query:
        args.query = input("问题: ").strip()
        if not args.query:
            print("请输入问题")
            sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
