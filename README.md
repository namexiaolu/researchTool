# ResearchTool

ResearchTool 是一个本地优先的调研、知识采集和 RAG 问答工具。它提供统一的
`research-tool` 命令。调研可直接调用本机 Codex、Claude Code、OpenCode 或 Grok，让工具使用
自己的 Web Search 与 MCP；RAG 问答继续支持 OpenAI Responses、Anthropic Messages、
Ollama 和 OpenCode Provider 档案。

## 安装

要求 Windows 11、PowerShell 7 和 Python 3.12 以上。

```powershell
$ErrorActionPreference = 'Stop'
Set-Location 'D:\AI\mySkill'
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -e '.[dev]'
& '.\.venv\Scripts\research-tool.exe' doctor
```

## 常用命令

```powershell
$ErrorActionPreference = 'Stop'
& '.\.venv\Scripts\research-tool.exe' research '调研主题' --update-index
& '.\.venv\Scripts\research-tool.exe' index update
& '.\.venv\Scripts\research-tool.exe' ask '问题'
& '.\.venv\Scripts\research-tool.exe' report '报告要求'
& '.\.venv\Scripts\research-tool.exe' menu
```

自动化调用在命令末尾添加 `--json`。最终 JSON 写入标准输出，结构化进度和诊断写入标准错误。
普通调研从第 0 秒实时显示工具和累计耗时；菜单 5 用于切换外部调研工具。

## 数据目录

```text
knowledge/          原始网页、论文和源码资料
reports/            AI 生成报告，不参与默认索引
.research-tool/     统一 JSON 配置，以及可重建的索引、缓存和状态
```

每份知识文件都有相邻的 `*.meta.json`，记录稳定 UUID、内容哈希、来源和采集时间。
`knowledge/`、`reports/` 与 `.research-tool/` 均不会提交到 Git。注意
`.research-tool/config.json` 包含 API Key，不是可随索引删除的缓存。

更多说明见 [架构](docs/architecture.md)、[CLI](docs/cli.md) 和
[配置](docs/configuration.md)。
