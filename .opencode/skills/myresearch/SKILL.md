---
name: myresearch
description: 通过 ResearchTool 对主题执行结构化网络与论文调研
trigger: /myresearch
---

# /myresearch

调用项目唯一入口 `research-tool`。CLI 会直接启动统一 JSON 中选择的 Codex、Claude Code、
OpenCode 或 Grok，由该工具使用自身 Web Search、MCP、模型与认证完成调研。

## Usage

```
/myresearch <topic>
```

## Execution

在项目根目录执行：

```powershell
$ErrorActionPreference = 'Stop'
research-tool research '<topic>' --json
```

不得在 Skill 中重新实现查询拆分、抓取、论文检索、去重或报告保存。需要让新资料立即可问答时，添加 `--update-index`。

## Output Format

```
命令返回 JSON，包含 `topic`、`report_path`、`items`、`failures`、`elapsed_seconds` 和可选的 `index`。
```

## Quality Criteria

- 将标准输出作为最终 JSON 解析。
- 将标准错误中的 JSON Lines 视为进度和诊断，不与最终 JSON 拼接。
- `failures` 非空表示部分来源失败，不代表整个任务失败。

## Edge Cases

| 场景 | 处理方式 |
|------|----------|
| 退出码非 0 | 向用户报告标准错误中的配置或任务错误 |
| `failures` 非空 | 展示失败项，同时保留成功报告 |
| 报告存在但未索引 | 按需再次执行 `research-tool index update` |
