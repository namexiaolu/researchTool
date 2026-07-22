from __future__ import annotations

import shutil
from dataclasses import replace

from rich.console import Console

from research_tool.cli.selector import MenuOption, choose_option
from research_tool.shared.settings import AppSettings, SettingsStore
from research_tool.shared.tooling import SUPPORTED_TOOLS, TOOL_COMMANDS, TOOL_LABELS


def select_research_tool(
    settings_store: SettingsStore,
    settings: AppSettings,
    console: Console,
) -> AppSettings:
    options = tuple(
        MenuOption(
            value=tool,
            label=("✓ " if tool == settings.active_tool else "") + TOOL_LABELS[tool],
            detail=(
                f"{TOOL_COMMANDS[tool]} · "
                f"{'已找到' if shutil.which(TOOL_COMMANDS[tool]) else '未找到'}"
            ),
        )
        for tool in SUPPORTED_TOOLS
    )
    selected = choose_option(
        console,
        "切换调研工具",
        options,
        initial_value=settings.active_tool,
    )
    if selected is None:
        return settings
    updated = replace(settings, active_tool=selected)
    settings_store.save(updated)
    console.print(
        f"[green]调研工具已切换[/]：{TOOL_LABELS[selected]}；"
        "运行时直接使用其本地配置和搜索能力"
    )
    return updated
