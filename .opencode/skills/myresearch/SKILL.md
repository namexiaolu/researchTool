---
name: myresearch
description: 使用 grok-search 对任何主题进行结构化 web 调研，返回结果
trigger: /myresearch
---

# /myresearch

使用 grok-search（MCP 工具）对指定主题进行多轮结构化搜索，输出带来源的可信结果。

## Usage

```
/myresearch <topic>                    # 标准调研
/myresearch <topic> --depth 3          # 深度调研（3轮搜索）
/myresearch <topic> --lang en          # 英文资料优先
```

## Execution

1. **生成调研计划** — 运行脚本生成子查询和搜索策略：

```powershell
python scripts/run_research.py --topic "<topic>" --depth <depth> --lang <lang>
```

2. **执行多轮搜索** — 根据计划中的 sub_queries，使用 grok-search：

```json
grok-search_plan_intent -> grok-search_plan_sub_query -> grok-search_web_search
```

每轮搜索收集结果后，标记已获取的信息，避免重复。

3. **验证与整合** — 交叉验证关键信息，标注来源，合并为结构化输出。

## Output Format

```
## Topic

一句话说明研究主题。

## Summary

核心结论，2-5 句话。

## Details

使用表格或分点呈现，每个结论附来源链接。
如果存在多个对比方案，优先用表格。

## Recommendation

推荐方案及理由（如适用）。

## Sources

列出来源链接，标注时效性。
```

## Quality Criteria

- 每个结论至少 2 个独立来源验证
- 明确区分事实与推测
- 标注信息的时效性（年份）
- 涉及开源项目时标注许可证类型
- 无结果时使用同义词或英文搜索兜底

## Edge Cases

| 场景 | 处理方式 |
|------|----------|
| 搜索无结果 | 切换英文/同义词重试 |
| 信息矛盾 | 标记冲突并说明分歧来源 |
| 链接失效 | 注明并尝试 archive.org 替代 |
| 主题过宽 | 自动拆分为子主题分别调研 |
