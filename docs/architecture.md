# 架构

## 模块

```text
src/research_tool/
├── cli/        命令、调研工具选择、实时进度、Rich 与 JSON 输出
├── research/   外部工具执行器和结果模型
├── knowledge/  文件仓储、UUID、哈希与 sidecar 元数据
├── rag/        文档加载、分块、增量清单、Chroma、问答和报告
├── llm/        Provider 档案及问答/报告生成适配器
└── shared/     路径、版本化 JSON、工具元数据、格式导入、异常和进度事件
```

## 两条 AI 路径

调研和 RAG 生成现在明确分离：

1. 功能 1/`research` 读取 `active_tool`，直接启动 Codex、Claude Code、OpenCode 或 Grok。
2. 菜单 3/4、`ask` 和 `report` 读取 `active_provider`，使用内部 ProviderFactory。

外部工具执行器负责构造安全的非交互命令、等待和取消进程、提取最终文本并原子保存报告。
报告完成后，证据采集器解析来源链接，将网页正文快照、代码仓库页面、论文页面和 PDF 归档到
知识库。搜索、认证、模型、MCP 和模型重试策略仍由外部工具自己负责。

旧的内部查询拆分、网页抓取、论文搜索和统一 MCP 编排已删除，调研入口不存在备用内部链路。

## 工具调用

- npm 安装的 `.CMD` 入口会自动改用同目录 `.ps1`，由 PowerShell 7 非交互启动。
- Codex 显式启用 `--search` 和只读 sandbox。
- Claude Code 使用 print/text 模式并加载本地配置。
- OpenCode 使用 JSON 事件输出，不加 `--pure`。
- Grok 使用 single/plain 模式，默认保留 Web Search。

工具进程没有响应超时。取消时先终止，2 秒内未退出则强制结束。执行器并行读取 stdout 和
stderr，在保留完整最终文本用于报告的同时，将安全的文本、搜索、抓取和工具调用状态发送给
`ProgressRenderer`。渲染器持续显示工具名、最新输出和累计耗时；隐藏推理块不会显示。

## 数据所有权

- `reports/` 只保存最终 Markdown 报告，不参与默认 RAG 索引。
- `knowledge/web/` 保存报告引用的网页正文快照。
- `knowledge/papers/` 保存论文页面、论文元数据和允许下载的 PDF。
- `knowledge/sources/` 保存 GitHub、GitLab、Gitee 等代码仓库或源码页面快照。
- RAG 默认只索引 `knowledge/` 中采集到的原始证据，不索引 AI 生成报告。
- `.research-tool/config.json` 保存活动工具、Provider 档案和应用设置。
- `.research-tool/index`、`cache` 和 `state` 是可重建派生数据。
