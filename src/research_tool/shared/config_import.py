from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from research_tool.shared.errors import ConfigurationError
from research_tool.shared.settings import AppSettings, ProviderProfile


@dataclass(frozen=True)
class ImportedProfiles:
    source_format: str
    profiles: dict[str, ProviderProfile]
    preferred_active: str


def load_json_source(source: str) -> dict[str, object]:
    normalized = source.strip()
    if not normalized:
        raise ConfigurationError("JSON 输入不能为空。")

    content = normalized
    if not normalized.startswith(("{", "[")):
        path = Path(normalized).expanduser()
        if not path.is_file():
            raise ConfigurationError(f"JSON 文件不存在：{path}")
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigurationError(f"无法读取 JSON 文件 {path}：{exc}") from exc

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"JSON 格式无效：{exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationError("导入内容必须是 JSON 对象。")
    return data


def import_profiles(data: dict[str, object]) -> ImportedProfiles:
    if "profiles" in data or "active_provider" in data:
        settings = AppSettings.from_dict(data)
        return ImportedProfiles("research-tool", settings.profiles, settings.active_provider)

    values = _flatten_environment(data)
    if _looks_like_claude(values):
        return _import_claude(data, values)
    if _looks_like_codex(data, values):
        return _import_codex(data, values)
    raise ConfigurationError(
        "无法识别 JSON 配置格式；需要 ResearchTool、Codex/OpenAI 或 Claude Code 字段。"
    )


def _import_codex(
    data: dict[str, object], values: dict[str, object]
) -> ImportedProfiles:
    provider_id = _value(data.get("model_provider"), "codex")
    provider_data = _provider_data(data, provider_id)
    auth = data.get("auth")
    auth_data = auth if isinstance(auth, dict) else {}
    api_key = _first(
        values.get("OPENAI_API_KEY"),
        auth_data.get("OPENAI_API_KEY"),
        data.get("api_key"),
        data.get("apiKey"),
    )
    base_url = _first(
        values.get("OPENAI_BASE_URL"),
        provider_data.get("base_url"),
        data.get("base_url"),
        data.get("baseUrl"),
    )
    model = _first(values.get("OPENAI_MODEL"), data.get("model"), "gpt-5")
    effort = _first(
        values.get("OPENAI_REASONING_EFFORT"), data.get("model_reasoning_effort")
    )
    name = _profile_name(provider_id, "codex-import")
    profile = ProviderProfile.from_dict(
        name,
        {
            "protocol": "openai-responses",
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "reasoning_effort": effort,
            "store": not bool(data.get("disable_response_storage", False)),
        },
    )
    return ImportedProfiles("codex", {name: profile}, name)


def _import_claude(
    data: dict[str, object], values: dict[str, object]
) -> ImportedProfiles:
    auth_token = _first(values.get("ANTHROPIC_AUTH_TOKEN"), data.get("auth_token"))
    api_key = _first(
        auth_token,
        values.get("ANTHROPIC_API_KEY"),
        data.get("api_key"),
        data.get("apiKey"),
    )
    model = _first(
        values.get("ANTHROPIC_MODEL"),
        values.get("ANTHROPIC_DEFAULT_SONNET_MODEL"),
        data.get("model"),
        "claude-sonnet-4-5",
    )
    base_url = _first(
        values.get("ANTHROPIC_BASE_URL"), data.get("base_url"), data.get("baseUrl")
    )
    name = _profile_name(_value(data.get("name"), "claude-import"), "claude-import")
    profile = ProviderProfile.from_dict(
        name,
        {
            "protocol": "anthropic-messages",
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "auth_mode": "bearer" if auth_token else "api-key",
        },
    )
    return ImportedProfiles("claude-code", {name: profile}, name)


def _flatten_environment(data: dict[str, object]) -> dict[str, object]:
    values = dict(data)
    environment = data.get("env") or data.get("environment")
    if isinstance(environment, dict):
        values.update(environment)
    return values


def _provider_data(data: dict[str, object], provider_id: str) -> dict[str, object]:
    providers = data.get("model_providers") or data.get("providers")
    if not isinstance(providers, dict):
        return {}
    selected = providers.get(provider_id)
    return selected if isinstance(selected, dict) else {}


def _looks_like_claude(values: dict[str, object]) -> bool:
    return any(str(key).startswith("ANTHROPIC_") for key in values)


def _looks_like_codex(data: dict[str, object], values: dict[str, object]) -> bool:
    return (
        any(str(key).startswith("OPENAI_") for key in values)
        or "model_provider" in data
        or "model_providers" in data
        or "wire_api" in data
    )


def _profile_name(value: str, default: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in value.strip().lower()
    ).strip("-._")
    return normalized[:64] or default


def _value(value: object, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _first(*values: object) -> str:
    for value in values:
        text = _value(value)
        if text:
            return text
    return ""
