from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @classmethod
    def discover(cls, start: Path | None = None) -> ProjectPaths:
        configured = os.getenv("RESEARCH_TOOL_ROOT", "").strip()
        if configured:
            return cls(Path(configured).expanduser().resolve())

        candidate = (start or Path.cwd()).resolve()
        for directory in (candidate, *candidate.parents):
            if (directory / "pyproject.toml").is_file():
                return cls(directory)
        return cls(candidate)

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    @property
    def runtime(self) -> Path:
        return self.root / ".research-tool"

    @property
    def index(self) -> Path:
        return self.runtime / "index"

    @property
    def cache(self) -> Path:
        return self.runtime / "cache"

    @property
    def state(self) -> Path:
        return self.runtime / "state"

    @property
    def settings(self) -> Path:
        return self.runtime / "config.json"

    def ensure_layout(self) -> None:
        for directory in (
            self.knowledge / "web",
            self.knowledge / "papers",
            self.knowledge / "sources",
            self.reports,
            self.index,
            self.cache,
            self.state,
        ):
            directory.mkdir(parents=True, exist_ok=True)
