from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from research_tool.knowledge.repository import KnowledgeRepository
from research_tool.research.evidence import EvidenceCollector
from research_tool.research.tool_runner import (
    ToolInvocation,
    ToolResearchRunner,
    _extract_report,
    _tool_failure_detail,
    _visible_tool_output,
    build_tool_invocation,
)
from research_tool.shared.events import ProgressEvent


@pytest.mark.parametrize(
    ("tool", "required", "forbidden"),
    [
        ("codex", {"--search", "exec", "--sandbox", "read-only"}, set()),
        ("claudecode", {"--print", "--permission-mode", "plan"}, set()),
        ("opencode", {"run", "--format", "json"}, {"--pure"}),
        ("grok", {"--single", "--output-format", "plain"}, {"--disable-web-search"}),
    ],
)
def test_build_tool_invocation_uses_each_tool_native_search_environment(
    tmp_path, monkeypatch, tool: str, required: set[str], forbidden: set[str]
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pwsh = bin_dir / "pwsh.exe"
    pwsh.write_bytes(b"")
    command_paths: dict[str, Path] = {"pwsh": pwsh}
    for command in ("codex", "claude", "opencode"):
        cmd = bin_dir / f"{command}.CMD"
        script = bin_dir / f"{command}.ps1"
        cmd.write_bytes(b"")
        script.write_text("", encoding="utf-8")
        command_paths[command] = cmd
    grok = bin_dir / "grok.exe"
    grok.write_bytes(b"")
    command_paths["grok"] = grok
    monkeypatch.setattr(
        "research_tool.research.tool_runner.shutil.which",
        lambda name: str(command_paths[name]) if name in command_paths else None,
    )

    invocation = build_tool_invocation(tool, "topic", tmp_path)

    assert required.issubset(invocation.args)
    assert forbidden.isdisjoint(invocation.args)
    assert invocation.args[-1] == "topic"
    if tool == "grok":
        assert invocation.command == str(grok)
    else:
        assert invocation.command == str(pwsh)
        assert "-File" in invocation.args
    if tool == "claudecode":
        assert invocation.args[-2:] == ("--", "topic")


@pytest.mark.asyncio
async def test_tool_runner_saves_report_and_original_evidence(tmp_path, monkeypatch) -> None:
    events: list[ProgressEvent] = []
    repository = KnowledgeRepository(tmp_path / "knowledge")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><title>原始网页</title><main>原始证据正文</main></html>",
        )

    runner = ToolResearchRunner(
        tool="codex",
        project_root=tmp_path,
        repository=repository,
        reports_dir=tmp_path / "reports",
        progress=events.append,
        evidence_collector=EvidenceCollector(
            repository,
            progress=events.append,
            transport=httpx.MockTransport(handler),
        ),
    )

    monkeypatch.setattr(
        "research_tool.research.tool_runner.build_tool_invocation",
        lambda tool, prompt, root: ToolInvocation("codex", (prompt,)),
    )

    async def fake_execute(invocation: ToolInvocation) -> tuple[str, str, int]:
        assert "主动使用" in invocation.args[0]
        return "# 调研结果\n\n结论，来源：https://example.com", "", 0

    monkeypatch.setattr(runner, "_execute", fake_execute)

    result = await runner.run("topic")

    assert result.report_path.is_file()
    assert len(result.items) == 1
    assert result.failures == ()
    assert result.items[0].path.is_file()
    assert result.items[0].source_url == "https://example.com"
    assert "原始证据正文" in result.items[0].path.read_text(encoding="utf-8")
    assert "# 调研结果" not in result.items[0].path.read_text(encoding="utf-8")
    assert "Codex" in result.report_path.read_text(encoding="utf-8")
    assert events[0].stage == "tool"
    assert events[-1].stage == "complete"


def test_extracts_opencode_json_text_events() -> None:
    stdout = "\n".join(
        [
            json.dumps({"type": "step_start"}),
            json.dumps({"type": "text", "part": {"text": "# Report"}}),
            json.dumps({"type": "text", "part": {"text": "\nBody"}}),
        ]
    )

    assert _extract_report("opencode", stdout) == "# Report\nBody"


def test_visible_opencode_output_filters_reasoning_and_describes_tools() -> None:
    text_event = json.dumps({"type": "text", "part": {"text": "正在整理结果"}})
    reasoning_event = json.dumps(
        {"type": "reasoning_summary", "part": {"text": "hidden"}}
    )
    tool_event = json.dumps(
        {
            "type": "tool_use",
            "part": {"tool": "web_search", "state": {"status": "running"}},
        }
    )

    assert _visible_tool_output("opencode", "stdout", text_event) == ("正在整理结果",)
    assert _visible_tool_output("opencode", "stdout", reasoning_event) == ()
    assert _visible_tool_output("opencode", "stdout", tool_event) == (
        "调用工具：web_search（running）",
    )


def test_extracts_readable_opencode_failure_detail() -> None:
    stdout = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "UnknownError",
                "data": {"message": "Unexpected server error.", "ref": "err_123"},
            },
        }
    )

    assert _tool_failure_detail("opencode", "", stdout) == (
        "Unexpected server error.（ref: err_123）"
    )


@pytest.mark.asyncio
async def test_execute_streams_visible_output_while_capturing_full_text(
    tmp_path, monkeypatch
) -> None:
    stdout = asyncio.StreamReader()
    stdout.feed_data(b"visible result\nthinking: private chain\n")
    stdout.feed_eof()
    stderr = asyncio.StreamReader()
    stderr.feed_data(b"searching web\ninternal detail\n")
    stderr.feed_eof()

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = stdout
            self.stderr = stderr

        async def wait(self) -> int:
            return 0

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(
        "research_tool.research.tool_runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    events: list[ProgressEvent] = []
    runner = ToolResearchRunner(
        tool="codex",
        project_root=tmp_path,
        repository=KnowledgeRepository(tmp_path / "knowledge"),
        reports_dir=tmp_path / "reports",
        progress=events.append,
    )

    captured_stdout, captured_stderr, returncode = await runner._execute(
        ToolInvocation("codex", ())
    )

    assert returncode == 0
    assert "thinking: private chain" in captured_stdout
    assert "internal detail" in captured_stderr
    visible = [event.message for event in events if event.stage == "tool-output"]
    assert visible == ["visible result", "searching web"]
    assert _extract_report("codex", captured_stdout) == "visible result"
