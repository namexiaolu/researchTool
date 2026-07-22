from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import sys
from collections.abc import Mapping
from dataclasses import replace
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from research_tool.cli.progress import ProgressRenderer
from research_tool.cli.provider_menu import merge_imported_profiles
from research_tool.cli.runtime import Runtime
from research_tool.cli.selector import MenuOption, choose_option
from research_tool.cli.tool_menu import select_research_tool
from research_tool.rag.assistant import AnswerService, ReportService
from research_tool.rag.models import AnswerResult
from research_tool.research.models import ResearchResult
from research_tool.research.tool_runner import ToolResearchRunner
from research_tool.shared.config_import import import_profiles, load_json_source
from research_tool.shared.errors import ResearchToolError
from research_tool.shared.events import ProgressCallback, ProgressEvent
from research_tool.shared.tooling import TOOL_COMMANDS, TOOL_LABELS


def _configure_utf8_streams() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


_configure_utf8_streams()
app = typer.Typer(no_args_is_help=True, help="本地调研、知识库和 RAG 助手。")
index_app = typer.Typer(no_args_is_help=True, help="管理 RAG 索引。")
config_app = typer.Typer(no_args_is_help=True, help="管理项目 JSON 配置。")
app.add_typer(index_app, name="index")
app.add_typer(config_app, name="config")
console = Console()
error_console = Console(stderr=True)


def _progress(event: ProgressEvent) -> None:
    error_console.print(f"[dim][{event.stage}][/] {event.message}")


def _json(data: Mapping[str, object]) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _fail(exc: Exception) -> None:
    error_console.print(f"[bold red]操作失败：[/]{exc}")
    raise typer.Exit(code=1) from exc


async def _execute_research(
    topic: str,
    *,
    download_papers: bool,
    update_index: bool,
    progress: ProgressCallback | None,
) -> tuple[ResearchResult, dict[str, object] | None]:
    runtime = Runtime.create(progress)
    result = await ToolResearchRunner(
        tool=runtime.settings.active_tool,
        project_root=runtime.paths.root,
        repository=runtime.knowledge,
        reports_dir=runtime.paths.reports,
        progress=progress,
    ).run(topic, download_papers=download_papers)
    index_result = runtime.index.update().to_dict() if update_index else None
    return result, index_result


@app.command("research")
def research_command(
    topic: Annotated[str, typer.Argument(help="调研主题。")],
    download_papers: Annotated[
        bool,
        typer.Option(
            "--download-papers/--no-download-papers",
            help="是否要求外部工具优先提供开放 PDF 链接。",
        ),
    ] = True,
    update_index: Annotated[
        bool, typer.Option("--update-index", help="调研完成后显式更新索引。")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", help="关闭调研过程输出。")] = False,
) -> None:
    try:
        with ProgressRenderer(
            error_console,
            json_lines=json_output,
            quiet=quiet,
        ) as progress:
            result, index_result = asyncio.run(
                _execute_research(
                    topic,
                    download_papers=download_papers,
                    update_index=update_index,
                    progress=progress,
                )
            )
    except KeyboardInterrupt:
        error_console.print("[yellow]用户已取消；已完成的资料仍保留在 knowledge/。[/]")
        raise typer.Exit(code=130) from None
    except (ResearchToolError, OSError, ValueError) as exc:
        _fail(exc)
    payload = result.to_dict()
    payload["index"] = index_result
    if json_output:
        _json(payload)
        return
    console.print(f"[bold green]调研完成[/]：{result.report_path}")
    console.print(f"原始证据：{len(result.items)}，采集失败：{len(result.failures)}")


@index_app.command("update")
def index_update(
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    try:
        result = Runtime.create(_progress).index.update()
    except Exception as exc:
        _fail(exc)
    if json_output:
        _json(result.to_dict())
    else:
        console.print(
            f"[green]索引已更新[/]：扫描 {result.scanned}，新增 {result.added}，"
            f"更新 {result.updated}，删除 {result.deleted}，新分块 {result.chunks}"
        )


@index_app.command("rebuild")
def index_rebuild(
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    try:
        result = Runtime.create(_progress).index.update(rebuild=True)
    except Exception as exc:
        _fail(exc)
    if json_output:
        _json(result.to_dict())
    else:
        console.print(f"[green]索引已重建[/]：{result.scanned} 个文档，{result.chunks} 个分块")


@index_app.command("status")
def index_status(
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    try:
        status = Runtime.create().index.status()
    except Exception as exc:
        _fail(exc)
    if json_output:
        _json(status.to_dict())
    else:
        state = "可用" if status.ready else "未建立"
        console.print(f"索引：{state}，文档 {status.document_count}，分块 {status.chunk_count}")


async def _answer(question: str, provider: str | None, top_k: int) -> AnswerResult:
    runtime = Runtime.create(_progress)
    llm = runtime.providers.create(provider)
    return await AnswerService(runtime.index, llm).ask(question, top_k=top_k)


@app.command("ask")
def ask_command(
    question: Annotated[str, typer.Argument(help="知识库问题。")],
    provider: Annotated[str | None, typer.Option("--provider", help="Provider 档案名。")] = None,
    top_k: Annotated[int, typer.Option("--top-k", min=1, max=20)] = 5,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    try:
        result = asyncio.run(_answer(question, provider, top_k))
    except Exception as exc:
        _fail(exc)
    if json_output:
        _json(result.to_dict())
        return
    console.print(f"[bold cyan]回答[/]\n{result.answer}\n")
    console.print("[dim]参考来源[/]")
    for source in result.sources:
        console.print(f"- {source}")
    error_console.print(f"[dim]AI 后端：{result.provider}[/]")


@app.command("report")
def report_command(
    request: Annotated[str, typer.Argument(help="报告要求。")],
    provider: Annotated[str | None, typer.Option("--provider", help="Provider 档案名。")] = None,
    top_k: Annotated[int, typer.Option("--top-k", min=1, max=20)] = 8,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    try:
        runtime = Runtime.create(_progress)
        llm = runtime.providers.create(provider)
        result, path = asyncio.run(
            ReportService(
                AnswerService(runtime.index, llm), runtime.paths.reports
            ).generate(request, top_k=top_k)
        )
    except Exception as exc:
        _fail(exc)
    payload = {"report_path": str(path), "answer": result.to_dict()}
    if json_output:
        _json(payload)
    else:
        console.print(f"[bold green]报告已保存[/]：{path}")
        console.print(result.answer)


@config_app.command("show")
def config_show(
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    try:
        runtime = Runtime.create()
        settings = runtime.settings
    except Exception as exc:
        _fail(exc)
    if json_output:
        _json(settings.to_public_dict())
        return
    table = Table("设置", "值")
    table.add_row("配置文件", str(runtime.paths.settings))
    table.add_row("调研工具", TOOL_LABELS[settings.active_tool])
    table.add_row("活动档案", settings.active_provider)
    table.add_row("协议", settings.active_profile.protocol)
    table.add_row("模型", settings.active_profile.model)
    table.add_row("档案数", str(len(settings.profiles)))
    table.add_row("Embedding", settings.embedding_model)
    console.print(table)


@config_app.command("set-provider")
def config_set_provider(
    profile: Annotated[str, typer.Argument(help="已有 Provider 档案名。")],
    model: Annotated[str | None, typer.Option("--model", help="同时更新该档案模型。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    selected = profile.strip()
    try:
        runtime = Runtime.create()
        if selected not in runtime.settings.profiles:
            raise ValueError(f"Provider 档案不存在：{selected}")
        profiles = dict(runtime.settings.profiles)
        if model:
            profiles[selected] = replace(profiles[selected], model=model.strip())
        settings = replace(
            runtime.settings,
            active_provider=selected,
            profiles=profiles,
        )
        runtime.settings_store.save(settings)
    except Exception as exc:
        _fail(exc)
    payload = {
        "active_provider": selected,
        "model": settings.profiles[selected].model,
        "validated": False,
    }
    if json_output:
        _json(payload)
    else:
        console.print(f"[green]配置已保存，连接未验证[/]：{selected}")


@config_app.command("import-json")
def config_import_json(
    source: Annotated[str, typer.Argument(help="JSON 文件路径或 JSON 对象字符串。")],
    activate: Annotated[
        bool, typer.Option("--activate/--no-activate", help="是否激活导入档案。")
    ] = True,
    overwrite: Annotated[bool, typer.Option("--overwrite", help="覆盖同名档案。")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    try:
        imported = import_profiles(load_json_source(source))
        runtime = Runtime.create()
        settings = merge_imported_profiles(
            runtime.settings,
            imported,
            activate=activate,
            overwrite=overwrite,
        )
        runtime.settings_store.save(settings)
    except Exception as exc:
        _fail(exc)
    payload = {
        "format": imported.source_format,
        "profiles": list(imported.profiles),
        "active_provider": settings.active_provider,
        "validated": False,
    }
    if json_output:
        _json(payload)
    else:
        console.print(
            f"[green]配置已保存，连接未验证[/]：{', '.join(imported.profiles)}"
        )


@app.command("doctor")
def doctor_command(
    live: Annotated[
        bool, typer.Option("--live", help="显式检查当前 Provider 的真实连接。")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="输出机器可读 JSON。")] = False,
) -> None:
    try:
        runtime = Runtime.create()
        dependencies = {
            name: importlib.util.find_spec(name) is not None
            for name in ("typer", "rich", "httpx", "openai", "langchain_core", "chromadb")
        }
        try:
            provider = runtime.providers.create()
            provider_status = provider.health_check(live=live).to_dict()
        except Exception as exc:
            provider_status = {
                "provider": runtime.settings.active_provider,
                "ready": False,
                "message": str(exc),
            }
        tool_name = runtime.settings.active_tool
        tool_command = TOOL_COMMANDS[tool_name]
        tool_status = {
            "tool": tool_name,
            "ready": bool(shutil.which(tool_command)),
            "command": tool_command,
            "message": "使用工具自己的本地认证、模型和搜索配置",
        }
        payload: dict[str, object] = {
            "python": sys.version.split()[0],
            "project_root": str(runtime.paths.root),
            "config_path": str(runtime.paths.settings),
            "knowledge_documents": len(runtime.knowledge.list_documents()),
            "index": runtime.index.status().to_dict(),
            "provider": provider_status,
            "research_tool": tool_status,
            "dependencies": dependencies,
            "ok": sys.version_info >= (3, 12) and all(dependencies.values()),
        }
    except Exception as exc:
        _fail(exc)
    if json_output:
        _json(payload)
        return
    table = Table("检查项", "结果")
    table.add_row("Python", str(payload["python"]))
    table.add_row("项目目录", str(payload["project_root"]))
    table.add_row("配置文件", str(payload["config_path"]))
    table.add_row("知识文档", str(payload["knowledge_documents"]))
    table.add_row("索引", json.dumps(payload["index"], ensure_ascii=False))
    table.add_row("Provider", json.dumps(payload["provider"], ensure_ascii=False))
    table.add_row("调研工具", json.dumps(payload["research_tool"], ensure_ascii=False))
    table.add_row("依赖", "通过" if all(dependencies.values()) else "缺失")
    console.print(table)


@app.command("menu")
def menu_command() -> None:
    menu_options = (
        MenuOption("1", "调研", "调用当前调研工具"),
        MenuOption("2", "更新索引", "增量同步 knowledge/"),
        MenuOption("3", "生成报告", "使用当前 Provider"),
        MenuOption("4", "提问", "查询本地 RAG 索引"),
        MenuOption("5", "切换调研工具", "Codex / Claude Code / OpenCode / Grok"),
        MenuOption("0", "退出"),
    )
    while True:
        runtime = Runtime.create()
        status = runtime.index.status()
        profile = runtime.settings.active_profile
        console.print("\n[bold]ResearchTool[/]")
        console.print(
            f"索引：{'可用' if status.ready else '未建立'} | "
            f"调研工具：{TOOL_LABELS[runtime.settings.active_tool]} | "
            f"Provider：{runtime.settings.active_provider} / {profile.model}"
        )
        choice = choose_option(
            console,
            "请选择功能",
            menu_options,
            initial_value="1",
            cancel_value="0",
        )
        try:
            if choice in {None, "0"}:
                return
            if choice == "1":
                topic = typer.prompt("调研主题")
                update = typer.confirm("调研后更新索引？", default=False)
                with ProgressRenderer(error_console) as progress:
                    research_result, _ = asyncio.run(
                        _execute_research(
                            topic,
                            download_papers=True,
                            update_index=update,
                            progress=progress,
                        )
                    )
                console.print(f"报告：{research_result.report_path}")
            elif choice == "2":
                updated_index = runtime.index.update()
                console.print(f"索引完成：{updated_index.to_dict()}")
            elif choice == "3":
                request = typer.prompt("报告要求")
                llm = runtime.providers.create()
                _, path = asyncio.run(
                    ReportService(
                        AnswerService(runtime.index, llm), runtime.paths.reports
                    ).generate(request)
                )
                console.print(f"报告：{path}")
            elif choice == "4":
                question = typer.prompt("问题")
                answer = asyncio.run(
                    AnswerService(runtime.index, runtime.providers.create()).ask(question)
                )
                console.print(answer.answer)
            elif choice == "5":
                select_research_tool(runtime.settings_store, runtime.settings, console)
        except KeyboardInterrupt:
            error_console.print("[yellow]操作已取消；已完成的资料仍然保留。[/]")
        except Exception as exc:
            error_console.print(f"[red]操作失败：[/]{exc}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
