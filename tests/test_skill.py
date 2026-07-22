from __future__ import annotations

from pathlib import Path


def test_opencode_skill_is_a_thin_cli_adapter() -> None:
    root = Path(__file__).resolve().parents[1]
    skill = (root / ".opencode" / "skills" / "myresearch" / "SKILL.md").read_text(encoding="utf-8")

    assert "research-tool research '<topic>' --json" in skill
    assert not (root / ".opencode" / "skills" / "myresearch" / "scripts").exists()
