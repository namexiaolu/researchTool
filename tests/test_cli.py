from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from research_tool.cli.app import app

runner = CliRunner()


def test_doctor_json_is_machine_readable(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["doctor", "--json"],
        env={"RESEARCH_TOOL_ROOT": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["knowledge_documents"] == 0
    assert payload["research_tool"]["tool"] == "opencode"
    config_path = Path(payload["config_path"])
    assert config_path.name == "config.json"
    assert config_path.parent.name == ".research-tool"


def test_config_show_json_is_redacted(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["config", "show", "--json"],
        env={"RESEARCH_TOOL_ROOT": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["active_tool"] == "opencode"
    assert payload["active_provider"] == "ollama-local"
    assert payload["profiles"]["ollama-local"]["api_key"] == "未配置"


def test_config_set_provider_supports_json(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "config",
            "set-provider",
            "opencode-local",
            "--model",
            "model/test",
            "--json",
        ],
        env={"RESEARCH_TOOL_ROOT": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "active_provider": "opencode-local",
        "model": "model/test",
        "validated": False,
    }
    saved = json.loads((tmp_path / ".research-tool" / "config.json").read_text(encoding="utf-8"))
    assert saved["active_provider"] == "opencode-local"


def test_config_imports_claude_code_json(tmp_path) -> None:
    source = json.dumps(
        {
            "env": {
                "ANTHROPIC_AUTH_TOKEN": "secret-token",
                "ANTHROPIC_BASE_URL": "https://claude.example.com",
                "ANTHROPIC_MODEL": "claude-test",
            }
        }
    )

    result = runner.invoke(
        app,
        ["config", "import-json", source, "--json"],
        env={"RESEARCH_TOOL_ROOT": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["format"] == "claude-code"
    saved_text = (tmp_path / ".research-tool" / "config.json").read_text(encoding="utf-8")
    assert "secret-token" in saved_text
    assert "claude-main" not in result.stdout
    assert "secret-token" not in result.stdout


def test_menu_can_exit(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["menu"],
        input="0\n",
        env={"RESEARCH_TOOL_ROOT": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output


def test_menu_switches_research_tool(tmp_path) -> None:
    result = runner.invoke(
        app,
        ["menu"],
        input="5\n1\n0\n",
        env={"RESEARCH_TOOL_ROOT": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    assert "切换调研工具" in result.output
    assert "Codex" in result.output
    saved = json.loads((tmp_path / ".research-tool" / "config.json").read_text(encoding="utf-8"))
    assert saved["active_tool"] == "codex"
