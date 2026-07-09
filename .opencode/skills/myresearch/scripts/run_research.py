#!/usr/bin/env python3
"""
myresearch — structured web research planner using grok-search.

Usage:
    python scripts/run_research.py --topic "石油行业 1D 模型 开源"
    python scripts/run_research.py --topic "topic" --lang en
    python scripts/run_research.py --topic "topic" --depth 3
"""

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class SubQuery:
    id: str
    goal: str
    expected_output: str
    boundary: str
    tool_hint: str = "web_search"
    depends_on: str = ""


@dataclass
class SearchTerm:
    term: str
    purpose: str
    round: int = 1


@dataclass
class ResearchPlan:
    core_question: str
    query_type: str = "exploratory"
    time_sensitivity: str = "irrelevant"
    sub_queries: list = field(default_factory=list)
    search_terms: list = field(default_factory=list)
    output_format: str = "table"


def parse_args():
    parser = argparse.ArgumentParser(description="myresearch research planner")
    parser.add_argument("--topic", required=True, help="Research topic")
    parser.add_argument("--lang", default="zh", choices=["zh", "en"], help="Primary language")
    parser.add_argument("--depth", type=int, default=2, choices=[1, 2, 3],
                        help="Research depth: 1=quick, 2=standard, 3=deep")
    parser.add_argument("--output", default="plan", choices=["plan", "plan+report"],
                        help="Output type")
    return parser.parse_args()


def build_plan(topic: str, depth: int) -> ResearchPlan:
    plan = ResearchPlan(core_question=topic)

    if depth >= 1:
        plan.sub_queries.append(SubQuery(
            id="sq1", goal=f"搜索「{topic}」的基本信息",
            expected_output="核心概念、主流方案概述",
            boundary="仅限于概述，不深入细节"
        ))
        plan.search_terms.append(SearchTerm(term=topic, purpose="sq1"))

    if depth >= 2:
        plan.sub_queries.append(SubQuery(
            id="sq2", goal=f"搜索「{topic}」的英文资料",
            expected_output="国际上的主流方案和项目",
            boundary="不包含中文资料"
        ))
        plan.search_terms.append(SearchTerm(
            term=_en_fallback(topic), purpose="sq2", round=1
        ))

    if depth >= 3:
        plan.sub_queries.append(SubQuery(
            id="sq3", goal=f"搜索「{topic}」的最新进展和对比",
            expected_output="方案的优缺点对比、选型建议",
            boundary="不包含已收集过的资料"
        ))
        plan.search_terms.append(SearchTerm(
            term=f"{topic} 2025 2026 comparison", purpose="sq3", round=2
        ))

    return plan


def _en_fallback(zh_topic: str) -> str:
    """Simple conversion — in practice, use LLM for proper translation."""
    return zh_topic


def main():
    args = parse_args()
    plan = build_plan(args.topic, args.depth)

    output = {
        "plan": asdict(plan),
        "execution": {
            "note": "Run sub-queries in order using grok-search web_search tool. "
                    "For each sub-query, first use plan_intent to initialize, "
                    "then call web_search with search_terms.",
            "output_format": "## Topic\n\n## Summary\n\n## Details\n\n## Recommendation\n\n## Sources",
        }
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
