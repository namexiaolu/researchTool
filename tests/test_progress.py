from __future__ import annotations

import io
import json

from rich.console import Console

from research_tool.cli.progress import ProgressRenderer
from research_tool.shared.events import ProgressEvent


def test_json_progress_is_structured_and_immediate() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False)

    with ProgressRenderer(console, json_lines=True) as progress:
        progress(ProgressEvent("plan", "生成调研计划", data={"attempt": 1}))
        progress(
            ProgressEvent(
                "tool-output",
                "正在搜索官方资料",
                data={"tool": "codex", "tool_label": "Codex"},
            )
        )

    lines = stream.getvalue().splitlines()
    initial = json.loads(lines[0])
    event = json.loads(lines[1])
    output = json.loads(lines[2])
    assert initial["stage"] == "start"
    assert initial["elapsed_seconds"] >= 0
    assert event["stage"] == "plan"
    assert event["data"] == {"attempt": 1}
    assert output["stage"] == "tool-output"
    assert output["message"] == "正在搜索官方资料"


def test_progress_keeps_stage_and_shows_latest_tool_output() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, color_system=None)

    with ProgressRenderer(console) as progress:
        progress(ProgressEvent("tool", "启动 Codex"))
        progress(
            ProgressEvent(
                "tool-output",
                "正在搜索官方资料",
                data={"tool_label": "Codex"},
            )
        )
        console.print(progress._render_status())

    rendered = stream.getvalue()
    assert "[tool] 启动 Codex" in rendered
    assert "[Codex] 正在搜索官方资料" in rendered
    assert "↳ Codex：正在搜索官方资料" in rendered
