from __future__ import annotations

import json
import threading
import time
from types import TracebackType

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from research_tool.shared.events import ProgressEvent


class ProgressRenderer:
    def __init__(
        self,
        console: Console,
        *,
        json_lines: bool = False,
        quiet: bool = False,
    ) -> None:
        self.console = console
        self.json_lines = json_lines
        self.quiet = quiet
        self.started = 0.0
        self.stage = "start"
        self.message = "准备启动调研"
        self.latest_output = ""
        self.latest_output_tool = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._live: Live | None = None

    def __enter__(self) -> ProgressRenderer:
        self.started = time.perf_counter()
        if self.quiet:
            return self
        if self.json_lines:
            self._write_json(self.stage, self.message, {})
            return self
        if self.console.is_terminal:
            self._live = Live(
                self._render_status(),
                console=self.console,
                refresh_per_second=4,
                transient=False,
            )
            self._live.start(refresh=True)
            self._thread = threading.Thread(target=self._refresh, daemon=True)
            self._thread.start()
        else:
            self.console.print(f"[dim][{self.stage}][/] {self.message} | 0.0 秒")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        if self._live is not None:
            if exc_type is KeyboardInterrupt:
                self.stage = "cancelled"
                self.message = "用户已取消"
            self._live.update(self._render_status(), refresh=True)
            self._live.stop()

    def __call__(self, event: ProgressEvent) -> None:
        if self.quiet:
            return
        with self._lock:
            if event.stage == "tool-output":
                self._show_tool_output(event)
                return
            self.stage = event.stage
            self.message = event.message
            if self.json_lines:
                self._write_json(event.stage, event.message, event.data)
                return
            elapsed = self._elapsed()
            line = f"[dim][{event.stage}][/] {event.message} [dim]({elapsed:.1f} 秒)[/]"
            if self._live is not None:
                self._live.console.print(line)
                self._live.update(self._render_status(), refresh=True)
            else:
                self.console.print(line)

    def _refresh(self) -> None:
        while not self._stop.wait(1):
            with self._lock:
                if self._live is not None:
                    self._live.update(self._render_status(), refresh=True)

    def _show_tool_output(self, event: ProgressEvent) -> None:
        message = event.message.strip()
        if not message or message == self.latest_output:
            return
        self.latest_output = message
        self.latest_output_tool = str(
            event.data.get("tool_label") or event.data.get("tool") or "工具"
        )
        if self.json_lines:
            self._write_json(event.stage, event.message, event.data)
            return
        line = Text(f"[{self.latest_output_tool}] {message}", style="dim")
        if self._live is not None:
            self._live.console.print(line)
            self._live.update(self._render_status(), refresh=True)
        else:
            self.console.print(line)

    def _render_status(self) -> Group:
        elapsed = self._elapsed()
        lines = [Text(f"[{self.stage}] {self.message} | 已用 {elapsed:.1f} 秒", style="cyan")]
        if self.latest_output:
            lines.append(
                Text(
                    f"↳ {self.latest_output_tool}：{self.latest_output}",
                    style="bright_black",
                )
            )
        return Group(*lines)

    def _write_json(self, stage: str, message: str, data: dict[str, object]) -> None:
        payload = {
            "type": "progress",
            "stage": stage,
            "message": message,
            "elapsed_seconds": round(self._elapsed(), 3),
            "data": data,
        }
        print(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            file=self.console.file,
            flush=True,
        )

    def _elapsed(self) -> float:
        return max(0.0, time.perf_counter() - self.started) if self.started else 0.0
