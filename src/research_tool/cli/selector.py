from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

KeyReader = Callable[[], str]


@dataclass(frozen=True)
class MenuOption:
    value: str
    label: str
    detail: str = ""


def choose_option(
    console: Console,
    title: str,
    options: Sequence[MenuOption],
    *,
    initial_value: str | None = None,
    cancel_value: str | None = None,
    key_reader: KeyReader | None = None,
    interactive: bool | None = None,
) -> str | None:
    choices = tuple(options)
    if not choices:
        raise ValueError("选择项不能为空。")

    selected = next(
        (index for index, option in enumerate(choices) if option.value == initial_value),
        0,
    )
    use_keyboard = _supports_keyboard(console) if interactive is None else interactive
    if not use_keyboard:
        return _fallback_prompt(console, title, choices, cancel_value)

    read_key = key_reader or _read_windows_key
    with Live(
        _render_menu(title, choices, selected),
        console=console,
        auto_refresh=False,
        transient=True,
    ) as live:
        live.refresh()
        while True:
            key = read_key()
            if key == "up":
                selected = (selected - 1) % len(choices)
            elif key == "down":
                selected = (selected + 1) % len(choices)
            elif key in {"right", "enter"}:
                return choices[selected].value
            elif key in {"left", "escape"}:
                return cancel_value
            elif key.isdigit():
                shortcut = int(key) - 1
                if 0 <= shortcut < len(choices):
                    return choices[shortcut].value
                if key == "0":
                    return cancel_value
            live.update(_render_menu(title, choices, selected), refresh=True)


def _supports_keyboard(console: Console) -> bool:
    return os.name == "nt" and console.is_terminal and sys.stdin.isatty()


def _read_windows_key() -> str:
    import msvcrt

    key = msvcrt.getwch()
    if key in {"\x00", "\xe0"}:
        return {
            "H": "up",
            "P": "down",
            "K": "left",
            "M": "right",
        }.get(msvcrt.getwch(), "unknown")
    if key == "\r":
        return "enter"
    if key == "\x1b":
        return "escape"
    if key == "\x03":
        raise KeyboardInterrupt
    return key


def _render_menu(title: str, options: tuple[MenuOption, ...], selected: int) -> Group:
    rows: list[Text] = [Text(title, style="bold")]
    for index, option in enumerate(options):
        prefix = "❯ " if index == selected else "  "
        row = Text(f"{prefix}{option.label}")
        if option.detail:
            row.append(f"  {option.detail}", style="dim")
        if index == selected:
            row.stylize("bold white on dark_cyan")
        rows.append(row)
    rows.append(Text("↑/↓ 选择 · →/Enter 确认 · ←/Esc 返回 · 数字快捷键", style="dim"))
    return Group(*rows)


def _fallback_prompt(
    console: Console,
    title: str,
    options: tuple[MenuOption, ...],
    cancel_value: str | None,
) -> str | None:
    values = {option.value for option in options}
    for index, option in enumerate(options, 1):
        shortcut = option.value if option.value.isdigit() else str(index)
        console.print(f"{shortcut}. {option.label}")
    if "0" not in values:
        console.print("0. 返回")

    while True:
        selected = typer.prompt(title).strip()
        if selected in values:
            return selected
        if selected == "0":
            return cancel_value
        if selected.isdigit():
            index = int(selected) - 1
            if 0 <= index < len(options):
                return options[index].value
        console.print("[yellow]请输入有效编号。[/]")
