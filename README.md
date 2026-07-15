# ResearchTool — 个人知识库调研助手

集成网络搜索、论文检索、RAG 索引与多 AI 后端的个人知识管理工具。

## 功能

| # | 功能 | 说明 |
|---|------|------|
| 1 | **网络调研** | 自动拆分调研主题为子查询 → Grok web search → 抓取页面 → 分类存入 `knowledge/` |
| 2 | **RAG 索引** | 扫描 `knowledge/` 下 .md/.txt/.pdf 文件 → 分块 → bge 嵌入 → Chroma 向量库 |
| 3 | **调研报告** | 基于 RAG 检索结果 + AI 生成结构化中文报告 |
| 4 | **自由提问** | 对已索引知识库进行问答 |
| 5 | **切换 AI 后端** | 支持 Ollama / OpenAI / CCSwitch / OpenCode 四种后端 |

### 网络调研 (功能 1)

- Grok search API（OpenAI 兼容）执行搜索，含来源链接
- 自动抓取 HTML 页面（httpx + BeautifulSoup）或通过 browser-relay 渲染动态页面
- 自动分类：`papers/`（论文）、`reports/`（报告）、`sources/`（源码/文档）、`web/`（网页）
- **学术数据库检索**（步骤 4/7）：并发查询 arXiv API 和 Semantic Scholar API
  - arXiv：返回 title/authors/abstract/pdf_url，自动下载 PDF 到 `knowledge/papers/`
  - Semantic Scholar：返回元数据及开放获取 PDF 链接（限流自动重试 3s→10s→30s）
- 内置指数退避重试对抗 API 限流

### 知识库结构

```
knowledge/
├── papers/          # 论文元数据 .md + 原始 PDF
├── reports/         # AI 生成的调研报告
├── sources/         # GitHub 源码、文档、教程等
├── web/             # 普通网页快照
└── vector_store/    # Chroma 向量索引（自动生成）
```

## 快速开始

### 环境要求

- Python 3.12+
- `.venv/` 虚拟环境

### 启动

```bash
python 启动项目.py
```

主菜单交互界面：

```
========================================
        个人知识库助手
========================================
RAG 索引：已建立
AI 后端：OpenCode（可用）

1. 输入调研内容，自动搜索网络并分类保存到 knowledge
2. 执行 RAG 索引
3. 根据提示词生成调研报告
4. 自由提问
5. 切换 AI 后端（Ollama / OpenAI / CCSwitch / OpenCode）
0. 退出
```

### CLI 直接使用

```bash
# 问答
python -m cli.main "你的问题" --verbose --trace

# 文本生成
python -m cli.generate "写作提示词"

# 重建索引
python -m cli.indexer.build_index
```

## AI 后端配置

### OpenCode（默认）

从 `~/.config/opencode/opencode.json` 读取 API 凭据，无需额外配置。

### Ollama

```bash
ollama pull qwen3:0.6b
```

### OpenAI

设置环境变量：

```bash
set OPENAI_API_KEY=sk-xxx
set OPENAI_BASE_URL=https://api.openai.com/v1
set OPENAI_MODEL=gpt-4o
```

### CCSwitch

```bash
set CCSWITCH_API_KEY=sk-xxx
set CCSWITCH_API_URL=https://api.ccswitch.com/v1
```

## 依赖

- 运行时：`httpx`、`beautifulsoup4`、`openai`、`langchain`、`chromadb`、`sentence-transformers`（bge 模型）
- 索引：`PyPDFLoader`、`UnstructuredMarkdownLoader`、`RecursiveCharacterTextSplitter`
- CLI：`typer`、`rich`

## 二级目录

```
cli/              CLI 模块
  main.py         问答 CLI（typer）
  generate.py     文本生成 CLI（typer）
  llm_provider.py AI 后端统一接口
  researcher.py   调研引擎（Grok search + arXiv/Semantic Scholar）
indexer/          RAG 索引模块
  build_index.py  索引构建入口
  loaders.py      文件加载（.md/.txt/.pdf）
  splitter.py     中文友好分块
  store.py        Chroma 向量存储
scripts/          工具脚本
  clean_knowledge.py  知识库清理与去重
```

## 许可证

MIT
