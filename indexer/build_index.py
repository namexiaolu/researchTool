from pathlib import Path
from time import perf_counter
from indexer.loaders import load as load_doc
from indexer.splitter import get_splitter
from indexer.store import build

KNOWLEDGE_DIR = Path("knowledge")

def scan_and_build():
    started_at = perf_counter()
    supported = {".md", ".txt", ".pdf"}
    files = [p for p in KNOWLEDGE_DIR.rglob("*") if p.suffix.lower() in supported]

    if not files:
        print("没有找到可索引的文件（支持 .md .txt .pdf）")
        return

    print(f"[过程] 扫描完成：发现 {len(files)} 个可索引文件，开始加载...")
    all_docs = []
    for fp in files:
        try:
            docs = load_doc(fp)
            all_docs.extend(docs)
            print(f"  ✓ {fp.relative_to(KNOWLEDGE_DIR)} ({len(docs)} 段)")
        except Exception as e:
            print(f"  ✗ {fp.relative_to(KNOWLEDGE_DIR)}: {e}")

    splitter = get_splitter()
    chunks = splitter.split_documents(all_docs)
    print(f"\n[过程] 文档加载完成：{len(all_docs)} 个文档片段。")
    print(f"[过程] 分块完成：共 {len(chunks)} 个文本块。")

    print("正在构建向量索引（首次会下载 bge 嵌入模型，约 100MB）...")
    build(chunks)
    print(f"✓ 索引构建完成！耗时 {perf_counter() - started_at:.1f} 秒。")

if __name__ == "__main__":
    scan_and_build()
