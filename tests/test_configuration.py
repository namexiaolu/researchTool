from __future__ import annotations

import json

import pytest

from research_tool.shared.config_import import import_profiles
from research_tool.shared.errors import ConfigurationError
from research_tool.shared.settings import AppSettings, ProviderProfile, SettingsStore


def test_settings_store_creates_and_reads_canonical_json(tmp_path) -> None:
    store = SettingsStore(tmp_path / ".research-tool" / "config.json")

    settings = store.load()
    loaded = store.load()

    assert settings == loaded
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["active_tool"] == "opencode"
    assert payload["active_provider"] == "ollama-local"


def test_settings_store_normalizes_legacy_json_without_active_tool(tmp_path) -> None:
    store = SettingsStore(tmp_path / ".research-tool" / "config.json")
    payload = AppSettings().to_dict()
    del payload["active_tool"]
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    settings = store.load()

    assert settings.active_tool == "opencode"
    normalized = json.loads(store.path.read_text(encoding="utf-8"))
    assert normalized["active_tool"] == "opencode"


def test_settings_public_dict_redacts_secrets() -> None:
    settings = AppSettings(
        active_provider="private",
        profiles={
            "private": ProviderProfile(
                protocol="openai-responses",
                model="gpt-test",
                api_key="sk-1234567890",
                base_url="https://user:password@example.com/v1?token=secret",
            )
        },
    )

    public = json.dumps(settings.to_public_dict(), ensure_ascii=False)

    assert "sk-1234567890" not in public
    assert "password" not in public
    assert "token=secret" not in public
    assert "example.com" in public


def test_imports_codex_json_profile() -> None:
    imported = import_profiles(
        {
            "OPENAI_API_KEY": "secret",
            "OPENAI_BASE_URL": "https://openai.example.com/v1",
            "OPENAI_MODEL": "gpt-test",
            "model_provider": "work-proxy",
        }
    )

    profile = imported.profiles["work-proxy"]
    assert imported.source_format == "codex"
    assert profile.protocol == "openai-responses"
    assert profile.model == "gpt-test"


def test_imports_claude_code_environment() -> None:
    imported = import_profiles(
        {
            "env": {
                "ANTHROPIC_AUTH_TOKEN": "secret",
                "ANTHROPIC_BASE_URL": "https://claude.example.com",
                "ANTHROPIC_MODEL": "claude-test",
            }
        }
    )

    profile = imported.profiles["claude-import"]
    assert imported.source_format == "claude-code"
    assert profile.protocol == "anthropic-messages"
    assert profile.auth_mode == "bearer"


def test_rejects_unknown_json_format() -> None:
    with pytest.raises(ConfigurationError, match="无法识别"):
        import_profiles({"unknown": True})
