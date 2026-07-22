from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from research_tool.knowledge.repository import KnowledgeRepository
from research_tool.research.evidence import EvidenceCollector
from research_tool.research.models import ResearchResult
from research_tool.shared.errors import ConfigurationError, ResearchToolError
from research_tool.shared.events import ProgressCallback, emit
from research_tool.shared.tooling import TOOL_COMMANDS, TOOL_LABELS

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
OPERATION_MARKERS = (
    "search",
    "fetch",
    "tool",
    "mcp",
    "retry",
    "connect",
    "warning",
    "error",
    "failed",
    "搜索",
    "检索",
    "抓取",
    "工具",
    "重试",
    "连接",
    "警告",
    "错误",
    "失败",
)
HIDDEN_PREFIXES = (
    "analysis:",
    "thinking:",
    "reasoning:",
    "chain of thought:",
)
OUTPUT_LINE_LIMIT = 1200


@dataclass(frozen=True)
class ToolInvocation:
    command: str
    args: tuple[str, ...]


class ToolResearchRunner:
    def __init__(
        self,
        *,
        tool: str,
        project_root: Path,
        repository: KnowledgeRepository,
        reports_dir: Path,
        progress: ProgressCallback | None = None,
        evidence_collector: EvidenceCollector | None = None,
    ) -> None:
        if tool not in TOOL_LABELS:
            raise ConfigurationError(f"不支持的调研工具：{tool}")
        self.tool = tool
        self.project_root = project_root
        self.repository = repository
        self.reports_dir = reports_dir
        self.progress = progress
        self.evidence_collector = evidence_collector or EvidenceCollector(
            repository,
            progress=progress,
        )

    async def run(self, topic: str, *, download_papers: bool = True) -> ResearchResult:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("调研主题不能为空。")
        started = time.perf_counter()
        prompt = _research_prompt(normalized_topic, download_papers=download_papers)
        invocation = build_tool_invocation(self.tool, prompt, self.project_root)
        label = TOOL_LABELS[self.tool]
        emit(
            self.progress,
            "tool",
            f"启动 {label}，由工具自行搜索并生成报告",
            tool=self.tool,
            command=invocation.command,
        )
        stdout, stderr, returncode = await self._execute(invocation)
        if returncode != 0:
            detail = _tool_failure_detail(self.tool, stderr, stdout) or (
                f"进程退出码 {returncode}"
            )
            raise ResearchToolError(f"{label} 调研失败：{detail}")
        report = _extract_report(self.tool, stdout)
        if not report:
            detail = _last_nonempty(stderr) or "工具没有返回报告文本"
            raise ResearchToolError(f"{label} 调研失败：{detail}")

        report_path = self._save_report(normalized_topic, report)
        evidence = await self.evidence_collector.collect(
            report,
            download_papers=download_papers,
        )
        elapsed = time.perf_counter() - started
        emit(
            self.progress,
            "complete",
            f"{label} 调研完成",
            tool=self.tool,
            report_path=str(report_path),
            item_count=len(evidence.items),
            failure_count=len(evidence.failures),
            elapsed_seconds=elapsed,
        )
        return ResearchResult(
            topic=normalized_topic,
            report_path=report_path,
            items=evidence.items,
            failures=evidence.failures,
            elapsed_seconds=elapsed,
        )

    async def _execute(self, invocation: ToolInvocation) -> tuple[str, str, int]:
        process = await asyncio.create_subprocess_exec(
            invocation.command,
            *invocation.args,
            cwd=self.project_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            process.kill()
            await process.wait()
            raise ResearchToolError("无法读取外部工具输出。")
        stdout_bytes = bytearray()
        stderr_bytes = bytearray()
        readers = (
            asyncio.create_task(
                self._consume_stream(process.stdout, "stdout", stdout_bytes)
            ),
            asyncio.create_task(
                self._consume_stream(process.stderr, "stderr", stderr_bytes)
            ),
        )
        try:
            await asyncio.gather(*readers)
            returncode = await process.wait()
        except asyncio.CancelledError:
            for reader in readers:
                reader.cancel()
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
            await asyncio.gather(*readers, return_exceptions=True)
            raise
        stdout = bytes(stdout_bytes).decode("utf-8", errors="replace")
        stderr = bytes(stderr_bytes).decode("utf-8", errors="replace")
        return stdout, stderr, returncode

    async def _consume_stream(
        self,
        stream: asyncio.StreamReader,
        stream_name: str,
        captured: bytearray,
    ) -> None:
        while chunk := await stream.readline():
            captured.extend(chunk)
            decoded = chunk.decode("utf-8", errors="replace")
            for message in _visible_tool_output(self.tool, stream_name, decoded):
                emit(
                    self.progress,
                    "tool-output",
                    message,
                    tool=self.tool,
                    tool_label=TOOL_LABELS[self.tool],
                    stream=stream_name,
                )

    def _save_report(self, topic: str, report: str) -> Path:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.reports_dir / f"report-{_slug(topic)}-{timestamp}.md"
        content = (
            "# 调研报告\n\n"
            f"- 主题：{topic}\n"
            f"- 工具：{TOOL_LABELS[self.tool]}\n"
            f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
            f"{report.strip()}\n"
        )
        temporary = path.with_name(f"{path.name}.tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(path)
        return path


def build_tool_invocation(tool: str, prompt: str, project_root: Path) -> ToolInvocation:
    command_name = TOOL_COMMANDS.get(tool)
    if command_name is None:
        raise ConfigurationError(f"不支持的调研工具：{tool}")
    command, prefix = _resolve_command(command_name)
    root = str(project_root)
    if tool == "codex":
        args = (
            *prefix,
            "--search",
            "--no-alt-screen",
            "exec",
            "--ephemeral",
            "--color",
            "never",
            "--sandbox",
            "read-only",
            "-C",
            root,
            "--skip-git-repo-check",
            prompt,
        )
    elif tool == "claudecode":
        args = (
            *prefix,
            "--print",
            "--output-format",
            "text",
            "--no-session-persistence",
            "--permission-mode",
            "plan",
            "--add-dir",
            root,
            "--",
            prompt,
        )
    elif tool == "opencode":
        args = (*prefix, "run", "--format", "json", "--dir", root, prompt)
    else:
        args = (
            *prefix,
            "--output-format",
            "plain",
            "--no-alt-screen",
            "--permission-mode",
            "plan",
            "--cwd",
            root,
            "--single",
            prompt,
        )
    return ToolInvocation(command, args)


def _resolve_command(command_name: str) -> tuple[str, tuple[str, ...]]:
    executable = shutil.which(command_name)
    if not executable:
        raise ConfigurationError(f"没有找到本机工具命令：{command_name}")
    path = Path(executable)
    if path.suffix.lower() in {".cmd", ".bat"}:
        script = path.with_suffix(".ps1")
        shell = shutil.which("pwsh")
        if not script.is_file() or not shell:
            raise ConfigurationError(f"无法通过 PowerShell 启动工具：{path}")
        return shell, ("-NoProfile", "-NonInteractive", "-File", str(script))
    return executable, ()


def _extract_report(tool: str, stdout: str) -> str:
    if tool != "opencode":
        cleaned = ANSI_PATTERN.sub("", stdout)
        return "\n".join(
            line for line in cleaned.splitlines() if not _is_hidden_reasoning(line)
        ).strip()
    fragments: list[str] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part")
        if event.get("type") == "text" and isinstance(part, dict) and part.get("text"):
            fragments.append(str(part["text"]))
    return "".join(fragments).strip()


def _visible_tool_output(tool: str, stream_name: str, raw_line: str) -> tuple[str, ...]:
    clean = ANSI_PATTERN.sub("", raw_line).strip()
    if not clean:
        return ()
    if tool == "opencode" and stream_name == "stdout":
        return _visible_opencode_event(clean)
    if _is_hidden_reasoning(clean):
        return ()
    if stream_name == "stderr" and not any(
        marker in clean.lower() for marker in OPERATION_MARKERS
    ):
        return ()
    return tuple(_bounded_lines(clean))


def _visible_opencode_event(line: str) -> tuple[str, ...]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return () if _is_hidden_reasoning(line) else tuple(_bounded_lines(line))
    if not isinstance(event, dict):
        return ()
    event_type = str(event.get("type") or "").lower()
    if any(marker in event_type for marker in ("reasoning", "thinking", "analysis")):
        return ()
    part = event.get("part")
    if event_type == "text" and isinstance(part, dict):
        return tuple(_bounded_lines(str(part.get("text") or "")))
    if event_type in {"tool", "tool_use", "tool_result"} and isinstance(part, dict):
        name = str(part.get("tool") or part.get("name") or "外部工具")
        state = part.get("state")
        status = str(state.get("status") or "") if isinstance(state, dict) else ""
        suffix = f"（{status}）" if status else ""
        return (f"调用工具：{name}{suffix}",)
    if event_type == "step_start":
        return ("开始新的执行阶段",)
    if event_type == "step_finish":
        return ("当前执行阶段完成",)
    if event_type == "error":
        return tuple(_bounded_lines(_opencode_error(event)))
    return ()


def _opencode_error(event: dict[str, object]) -> str:
    error = event.get("error")
    if not isinstance(error, dict):
        return "OpenCode 返回错误事件"
    data = error.get("data")
    if isinstance(data, dict) and data.get("message"):
        reference = f"（ref: {data['ref']}）" if data.get("ref") else ""
        return f"OpenCode 错误：{data['message']}{reference}"
    return f"OpenCode 错误：{error.get('name') or '未知错误'}"


def _tool_failure_detail(tool: str, stderr: str, stdout: str) -> str:
    if tool == "opencode":
        for line in reversed(stdout.splitlines()):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "error":
                return _opencode_error(event).removeprefix("OpenCode 错误：")
    return _last_nonempty(stderr, stdout)


def _is_hidden_reasoning(line: str) -> bool:
    normalized = line.lstrip("#>*- ").lower()
    return normalized.startswith(HIDDEN_PREFIXES)


def _bounded_lines(value: str) -> list[str]:
    return [
        line.strip()[:OUTPUT_LINE_LIMIT]
        for line in value.splitlines()
        if line.strip()
    ]


def _research_prompt(topic: str, *, download_papers: bool) -> str:
    paper_requirement = (
        "优先检索论文与原始资料，并在来源中给出可公开访问的 PDF 链接。"
        if download_papers
        else "论文只需列出页面或 DOI，不必寻找 PDF 下载链接。"
    )
    return (
        "请对下面主题执行完整调研。必须主动使用你自身可用的 Web Search、Web Fetch 或 MCP "
        "搜索能力查找最新且可核验的资料，不要依赖记忆猜测。输出中文 Markdown 报告，包含标题、"
        "摘要、主要发现、对比分析、风险或局限、结论和来源链接。每项关键结论注明来源 URL。"
        "来源列表必须使用带标题的 Markdown 链接，并优先给出原始网页、官方文档、代码仓库、"
        f"论文页面或 PDF 的直接地址。{paper_requirement}只返回最终报告，不修改项目文件，"
        "不运行与调研无关的命令。\n\n"
        f"调研主题：{topic}"
    )


def _last_nonempty(*values: str) -> str:
    for value in values:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if lines:
            return ANSI_PATTERN.sub("", lines[-1])[-2000:]
    return ""


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", normalized).strip("-_")
    return normalized[:60] or "research"
