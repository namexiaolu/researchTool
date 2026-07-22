from __future__ import annotations

import os
import subprocess
import time

import pytest

from research_tool.research.tool_runner import _extract_report, build_tool_invocation
from research_tool.shared.paths import ProjectPaths
from research_tool.shared.tooling import SUPPORTED_TOOLS, TOOL_LABELS

LIVE_SMOKE_ENV = "RESEARCH_TOOL_LIVE_SMOKE"
EXPECTED_MARKER = "TOOL_SMOKE_OK"
SMOKE_PROMPT = (
    "这是一次本机 CLI 冒烟测试。不要搜索网络，不要读取或修改文件，不要调用任何工具。"
    f"你的完整输出必须且只能是：{EXPECTED_MARKER}"
)


@pytest.mark.live
@pytest.mark.parametrize("tool", SUPPORTED_TOOLS)
def test_local_tool_returns_smoke_marker(tool: str) -> None:
    if os.getenv(LIVE_SMOKE_ENV) != "1":
        pytest.skip(f"设置 {LIVE_SMOKE_ENV}=1 后运行真实工具测试")

    project_root = ProjectPaths.discover().root
    invocation = build_tool_invocation(tool, SMOKE_PROMPT, project_root)
    started = time.perf_counter()
    completed = subprocess.run(
        (invocation.command, *invocation.args),
        cwd=project_root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed = time.perf_counter() - started
    output = _extract_report(tool, completed.stdout)
    detail = _last_nonempty(completed.stderr, completed.stdout)

    assert completed.returncode == 0, (
        f"{TOOL_LABELS[tool]} 退出码 {completed.returncode}：{detail}"
    )
    assert EXPECTED_MARKER in output, (
        f"{TOOL_LABELS[tool]} 未返回测试标记；输出：{output[-1000:]}"
    )
    print(f"{TOOL_LABELS[tool]}: {EXPECTED_MARKER} ({elapsed:.2f}s)")


def _last_nonempty(*values: str) -> str:
    for value in values:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if lines:
            return lines[-1][-2000:]
    return "没有输出"
