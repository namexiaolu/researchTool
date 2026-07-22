from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from research_tool.shared.errors import ConfigurationError
from research_tool.shared.tooling import SUPPORTED_TOOLS

CONFIG_VERSION = 1
SUPPORTED_PROTOCOLS = ("ollama", "openai-responses", "anthropic-messages", "opencode")
SUPPORTED_AUTH_MODES = ("api-key", "bearer")
SUPPORTED_REASONING_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class ProviderProfile:
    protocol: str
    model: str
    api_key: str = ""
    base_url: str = ""
    reasoning_effort: str = ""
    auth_mode: str = "api-key"
    store: bool = False

    @classmethod
    def from_dict(cls, name: str, data: dict[str, object]) -> ProviderProfile:
        validate_profile_name(name)
        protocol = _required_text(data.get("protocol"), f"Provider 档案 {name} 缺少 protocol")
        if protocol not in SUPPORTED_PROTOCOLS:
            allowed = ", ".join(SUPPORTED_PROTOCOLS)
            raise ConfigurationError(
                f"Provider 档案 {name} 的 protocol 无效：{protocol}；可选 {allowed}"
            )

        model = _required_text(data.get("model"), f"Provider 档案 {name} 缺少 model")
        api_key = _text(data.get("api_key"))
        base_url = _text(data.get("base_url"))
        effort = _text(data.get("reasoning_effort")).lower()
        auth_mode = _text(data.get("auth_mode"), "api-key").lower()

        if protocol in {"openai-responses", "anthropic-messages"} and not api_key:
            raise ConfigurationError(f"Provider 档案 {name} 缺少 api_key")
        if base_url:
            _validate_http_url(base_url, f"Provider 档案 {name} 的 base_url")
        if effort and effort not in SUPPORTED_REASONING_EFFORTS:
            allowed = ", ".join(SUPPORTED_REASONING_EFFORTS)
            raise ConfigurationError(
                f"Provider 档案 {name} 的 reasoning_effort 无效；可选 {allowed}"
            )
        if auth_mode not in SUPPORTED_AUTH_MODES:
            allowed = ", ".join(SUPPORTED_AUTH_MODES)
            raise ConfigurationError(f"Provider 档案 {name} 的 auth_mode 无效；可选 {allowed}")

        return cls(
            protocol=protocol,
            model=model,
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            reasoning_effort=effort,
            auth_mode=auth_mode,
            store=_boolean(data.get("store"), False),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, object]:
        data = self.to_dict()
        data["api_key"] = redact_secret(self.api_key)
        data["base_url"] = redact_url(self.base_url)
        return data


def _default_profiles() -> dict[str, ProviderProfile]:
    return {
        "ollama-local": ProviderProfile(protocol="ollama", model="qwen3:0.6b"),
        "opencode-local": ProviderProfile(
            protocol="opencode", model="opencode/deepseek-v4-flash-free"
        ),
    }


@dataclass(frozen=True)
class AppSettings:
    version: int = CONFIG_VERSION
    active_tool: str = "opencode"
    active_provider: str = "ollama-local"
    profiles: dict[str, ProviderProfile] = field(default_factory=_default_profiles)
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    top_k: int = 5

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AppSettings:
        version = _integer(data.get("version"), CONFIG_VERSION)
        if version != CONFIG_VERSION:
            raise ConfigurationError(
                f"不支持的配置版本 {version}，当前仅支持 {CONFIG_VERSION}。"
            )

        active_tool = _text(data.get("active_tool"), cls.active_tool).lower()
        if active_tool not in SUPPORTED_TOOLS:
            allowed = ", ".join(SUPPORTED_TOOLS)
            raise ConfigurationError(f"不支持的调研工具：{active_tool}；可选 {allowed}")

        raw_profiles = data.get("profiles")
        if not isinstance(raw_profiles, dict) or not raw_profiles:
            raise ConfigurationError("配置必须包含非空 profiles JSON 对象。")
        profiles: dict[str, ProviderProfile] = {}
        for raw_name, raw_profile in raw_profiles.items():
            name = str(raw_name).strip()
            if not isinstance(raw_profile, dict):
                raise ConfigurationError(f"Provider 档案 {name} 必须是 JSON 对象。")
            profiles[name] = ProviderProfile.from_dict(name, raw_profile)

        active = _required_text(data.get("active_provider"), "缺少 active_provider")
        if active not in profiles:
            raise ConfigurationError(f"活动 Provider 档案不存在：{active}")

        settings = cls(
            version=version,
            active_tool=active_tool,
            active_provider=active,
            profiles=profiles,
            embedding_model=_required_text(
                data.get("embedding_model", cls.embedding_model), "缺少 embedding_model"
            ),
            top_k=_integer(data.get("top_k"), cls.top_k),
        )
        if settings.top_k < 1:
            raise ConfigurationError("top_k 必须大于 0。")
        return settings

    @property
    def active_profile(self) -> ProviderProfile:
        return self.profiles[self.active_provider]

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "active_tool": self.active_tool,
            "active_provider": self.active_provider,
            "profiles": {name: profile.to_dict() for name, profile in self.profiles.items()},
            "embedding_model": self.embedding_model,
            "top_k": self.top_k,
        }

    def to_public_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "active_tool": self.active_tool,
            "active_provider": self.active_provider,
            "profiles": {
                name: profile.to_public_dict() for name, profile in self.profiles.items()
            },
            "embedding_model": self.embedding_model,
            "top_k": self.top_k,
        }


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppSettings:
        if not self.path.is_file():
            settings = AppSettings()
            self.save(settings)
            return settings
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"无法读取项目配置 {self.path}：{exc}") from exc
        if not isinstance(data, dict):
            raise ConfigurationError(f"项目配置必须是 JSON 对象：{self.path}")
        settings = AppSettings.from_dict(data)
        if data != settings.to_dict():
            self.save(settings)
        return settings

    def save(self, settings: AppSettings) -> None:
        validated = AppSettings.from_dict(settings.to_dict())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        content = json.dumps(validated.to_dict(), ensure_ascii=False, indent=2) + "\n"
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(self.path)


def validate_profile_name(name: str) -> None:
    if not PROFILE_NAME_PATTERN.fullmatch(name):
        raise ConfigurationError(
            "Provider 档案名必须以字母或数字开头，且只包含字母、数字、点、下划线或连字符，"
            "最长 64 个字符。"
        )


def redact_secret(value: str) -> str:
    if not value:
        return "未配置"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-4:]}"


def redact_url(value: str) -> str:
    if not value:
        return "默认地址"
    parsed = urlparse(value)
    host = parsed.hostname or parsed.path
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}" if parsed.scheme else host


def _validate_http_url(value: str, field_name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"{field_name} 必须是有效的 HTTP(S) URL：{value}")


def _text(value: object, default: str = "") -> str:
    text = str(value).strip() if value is not None else ""
    return text or default


def _required_text(value: object, message: str) -> str:
    text = _text(value)
    if not text:
        raise ConfigurationError(message)
    return text


def _integer(value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ConfigurationError("布尔值不能作为整数设置。")
    try:
        return int(str(value))
    except ValueError as exc:
        raise ConfigurationError(f"整数设置无效：{value}") from exc


def _boolean(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"布尔设置无效：{value}")
