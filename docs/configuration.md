# 配置

`.research-tool/config.json` 是程序唯一读取的项目配置。首次运行会生成默认文件，后续缺失的
新字段会自动补齐并原子写回。目录已加入 `.gitignore`，其中的 Provider API Key 应按敏感
文件管理。

完整结构由 [config.schema.json](config.schema.json) 定义。核心结构示例：

```json
{
  "version": 1,
  "active_tool": "codex",
  "active_provider": "ollama-local",
  "profiles": {
    "ollama-local": {
      "protocol": "ollama",
      "model": "qwen3:0.6b",
      "api_key": "",
      "base_url": "",
      "reasoning_effort": "",
      "auth_mode": "api-key",
      "store": false
    },
    "opencode-local": {
      "protocol": "opencode",
      "model": "provider/model",
      "api_key": "",
      "base_url": "",
      "reasoning_effort": "",
      "auth_mode": "api-key",
      "store": false
    }
  },
  "embedding_model": "BAAI/bge-small-zh-v1.5",
  "top_k": 5
}
```

## 调研工具

`active_tool` 决定功能 1 和 `research-tool research` 直接启动哪个本机工具：

- `codex`：运行 `codex --search exec`，启用 Codex 原生 Web Search。
- `claudecode`：运行 `claude --print`，加载 Claude Code 自己的本地工具与 MCP 配置。
- `opencode`：运行 `opencode run`，不使用 `--pure`，保留 OpenCode 插件与 MCP。
- `grok`：运行 `grok --single`，保留 Grok 默认 Web Search 与 Web Fetch。

ResearchTool 不向这些工具注入 API Key、Base URL、模型或 MCP，也不读取它们的用户配置。
认证、模型和搜索能力全部由对应 CLI 自己管理。菜单 5 只保存选择，不发送请求或检查登录状态。

为降低副作用，Codex 使用只读 sandbox，Claude Code 与 Grok 使用 plan 权限模式；统一提示词要求
工具不得修改项目文件。OpenCode 使用其本地权限策略，未自动添加危险的 `--auto`。

## Provider 档案

Provider 档案继续服务于菜单 3/4 和 `ask`、`report`，与功能 1 的外部调研工具相互独立。
支持 `openai-responses`、`anthropic-messages`、`ollama` 和 `opencode`。普通界面和
`config show --json` 始终脱敏。

`config import-json` 接受 UTF-8 JSON 文件路径或 JSON 对象字符串，并自动识别内部、Codex
或 Claude Code 样式：

```powershell
$ErrorActionPreference = 'Stop'
research-tool config import-json '.\codex.json'
research-tool config import-json '.\claude-settings.json' --no-activate
research-tool config set-provider opencode-local
```

导入只影响 Provider 档案，不改变 `active_tool`。

## 项目根目录

CLI 从当前目录向上查找 `pyproject.toml`。自动化和测试可设置 `RESEARCH_TOOL_ROOT`
显式指定根目录；该变量只定位项目，不覆盖外部工具或 Provider 配置。
