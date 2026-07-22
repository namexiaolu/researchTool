from __future__ import annotations

from io import StringIO

from rich.console import Console

from research_tool.cli.selector import MenuOption, choose_option


def _reader(*keys: str):
    iterator = iter(keys)
    return lambda: next(iterator)


def _console() -> Console:
    return Console(file=StringIO(), force_terminal=True, color_system=None, width=100)


def test_keyboard_selector_moves_and_confirms() -> None:
    selected = choose_option(
        _console(),
        "选择",
        (MenuOption("a", "A"), MenuOption("b", "B"), MenuOption("c", "C")),
        key_reader=_reader("down", "down", "right"),
        interactive=True,
    )

    assert selected == "c"


def test_keyboard_selector_wraps_and_can_cancel() -> None:
    options = (MenuOption("a", "A"), MenuOption("b", "B"))

    wrapped = choose_option(
        _console(),
        "选择",
        options,
        key_reader=_reader("up", "enter"),
        interactive=True,
    )
    cancelled = choose_option(
        _console(),
        "选择",
        options,
        cancel_value="back",
        key_reader=_reader("left"),
        interactive=True,
    )

    assert wrapped == "b"
    assert cancelled == "back"


def test_keyboard_selector_supports_numeric_shortcuts() -> None:
    selected = choose_option(
        _console(),
        "选择",
        (MenuOption("codex", "Codex"), MenuOption("grok", "Grok")),
        key_reader=_reader("2"),
        interactive=True,
    )

    assert selected == "grok"
