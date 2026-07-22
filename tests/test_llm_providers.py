from __future__ import annotations

from research_tool.llm.providers import (
    AnthropicMessagesProvider,
    OllamaProvider,
    OpenAIResponsesProvider,
    OpenCodeProvider,
    ProviderFactory,
)
from research_tool.shared.settings import AppSettings, ProviderProfile


def _settings(name: str, profile: ProviderProfile) -> AppSettings:
    return AppSettings(active_provider=name, profiles={name: profile})


def test_factory_creates_ollama_from_json_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL", "must-not-be-read")
    settings = _settings(
        "local",
        ProviderProfile(
            protocol="ollama",
            model="qwen3:4b",
            base_url="http://127.0.0.1:11434",
        ),
    )

    provider = ProviderFactory(settings, tmp_path).create()

    assert isinstance(provider, OllamaProvider)
    assert provider.config.model == "qwen3:4b"
    assert provider.describe().startswith("local / Ollama")


def test_factory_creates_openai_adapter_without_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key-must-not-win")
    settings = _settings(
        "codex-main",
        ProviderProfile(
            protocol="openai-responses",
            model="gpt-test",
            api_key="json-secret",
            base_url="https://example.com/v1",
            reasoning_effort="high",
        ),
    )

    provider = ProviderFactory(settings, tmp_path).create()

    assert isinstance(provider, OpenAIResponsesProvider)
    assert provider.config.api_key == "json-secret"
    assert provider.config.reasoning_effort == "high"


def test_factory_creates_anthropic_adapter(tmp_path) -> None:
    settings = _settings(
        "claude-main",
        ProviderProfile(
            protocol="anthropic-messages",
            model="claude-test",
            api_key="secret",
            auth_mode="bearer",
        ),
    )

    provider = ProviderFactory(settings, tmp_path).create()

    assert isinstance(provider, AnthropicMessagesProvider)
    assert provider.config.auth_mode == "bearer"


def test_factory_creates_opencode_adapter_from_local_environment(tmp_path, monkeypatch) -> None:
    executable = tmp_path / "opencode.exe"
    executable.write_bytes(b"")
    monkeypatch.setattr("research_tool.llm.providers.shutil.which", lambda _: str(executable))
    settings = _settings(
        "opencode-work",
        ProviderProfile(protocol="opencode", model="provider/model"),
    )

    provider = ProviderFactory(settings, tmp_path).create()

    assert isinstance(provider, OpenCodeProvider)
    assert provider.config.model == "provider/model"
    assert provider.health_check().ready is True
