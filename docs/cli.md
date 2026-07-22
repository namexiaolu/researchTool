# CLI

所有操作都通过 `research-tool` 完成。

## 调研

```powershell
$ErrorActionPreference = 'Stop'
research-tool research '主题'
research-tool research '主题' --no-download-papers --update-index --json
research-tool research '主题' --quiet
```

命令直接启动菜单 5 选中的 Codex、Claude Code、OpenCode 或 Grok。外部工具自行使用其 Web
Search、Web Fetch 或 MCP，并返回最终 Markdown 报告；ResearchTool 不再代理 Grok API 或
统一搜索 MCP。

普通终端从第 0 秒显示当前工具和累计耗时，每秒刷新，并实时打印工具明确输出的文本、搜索、
抓取和工具调用状态。ANSI、OpenCode JSON 会被转换为可读文本；隐藏推理块不会显示。外部工具
请求不设响应超时，`Ctrl+C` 会终止子进程并保留已经落盘的资料。`--json` 将最终结果写 stdout，
结构化进度和工具输出事件写 stderr；`--quiet` 可关闭这些动态输出。

`--download-papers` 要求外部工具优先寻找开放 PDF 链接，并由 ResearchTool 在报告完成后下载
直接 PDF 或论文页面中发现的首个 PDF。`--no-download-papers` 仍会保存论文页面或链接元数据，
但不下载 PDF 二进制。

最终报告只写入 `reports/`。ResearchTool 会解析报告中的 Markdown 链接和裸 URL，将网页正文
快照写入 `knowledge/web/`，代码仓库快照写入 `knowledge/sources/`，论文页面、元数据和 PDF
写入 `knowledge/papers/`。单个来源采集失败不会丢失最终报告，并会出现在结果的 `failures` 中。

## 索引

```powershell
$ErrorActionPreference = 'Stop'
research-tool index update
research-tool index rebuild
research-tool index status --json
```

## 问答与报告

这些命令继续使用 Provider 档案，而不是菜单 5 的外部调研工具：

```powershell
$ErrorActionPreference = 'Stop'
research-tool ask '问题' --provider codex-main --top-k 5
research-tool report '报告要求' --provider opencode-local --top-k 8
```

## 配置与检查

```powershell
$ErrorActionPreference = 'Stop'
research-tool config show --json
research-tool config set-provider opencode-local
research-tool config import-json '.\claude-settings.json'
research-tool doctor --json
```

`doctor` 只检查活动工具命令是否存在，不调用工具或检测登录状态。

## 交互菜单

```powershell
$ErrorActionPreference = 'Stop'
research-tool menu
```

交互终端中使用 `↑/↓` 移动高亮项，`→` 或 Enter 确认，`←` 或 Esc 返回；数字键仍可作为
快捷键。重定向输入和自动化环境会自动回退到编号输入。

菜单 5 直接列出 Codex、Claude Code、OpenCode 和 Grok，并标记本机命令是否存在。选中后立即
写入统一 JSON，下一次功能 1 调研使用该工具自己的认证、模型和搜索配置。
