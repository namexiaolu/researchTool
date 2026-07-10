---
name: rag
description: 从本地 PDF、Word、Markdown、TXT 和已保存网页中检索信息（RAG）
trigger: /rag
---

# /rag

使用 `D:\AI\mySkill\rag\rag.py` CLI 工具进行本地知识库问答。

## Usage

```
/rag 你的问题                     # 直接问答
/rag build                        # 重建索引
/rag add-web <url>                # 添加网页
```

## 知识库目录

`~/.rag-knowledge/`
- `docs/` — 放入 PDF、.docx、.md、.txt
- `web/` — add-web 保存的网页
- `vector_store/` — chroma 向量库（自动生成）

## Execution

1. **检索** — 运行 `python rag.py query -q "问题"` 获取相关文本块
2. **回答** — 用检索到的文本块作为上下文，回答用户问题

如果 index 不存在或文件有变更，先执行 `build`。
