from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


SUPPORTED_PROVIDERS = {"ollama", "openai", "ccswitch", "opencode"}
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
SUPPORTED_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    model: str
    display_name: str
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str | None = None
    store: bool = False


def load_llm_config(provider: str | None = None) -> LlmConfig:
    selected = (provider or os.getenv("RAG_LLM_PROVIDER") or "ollama").strip().lower()
    if selected not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise ValueError(f"不支持的 AI 后端：{selected}。可选值：{supported}")

    if selected == "ollama":
        model = os.getenv("OLLAMA_MODEL", "qwen3:0.6b").strip()
        return LlmConfig(
            provider="ollama",
            model=model,
            display_name=f"Ollama / {model}",
        )

    if selected == "openai":
        api_key = _required_value(os.getenv("OPENAI_API_KEY"), "缺少 OPENAI_API_KEY")
        model = os.getenv("OPENAI_MODEL", "gpt-5.6").strip()
        base_url = _optional_value(os.getenv("OPENAI_BASE_URL"))
        reasoning_effort = _reasoning_effort(
            os.getenv("OPENAI_REASONING_EFFORT", "low")
        )
        return LlmConfig(
            provider="openai",
            model=model,
            display_name=f"OpenAI / {model}",
            api_key=api_key,
            base_url=base_url,
            reasoning_effort=reasoning_effort,
        )

    if selected == "opencode":
        return _load_opencode_config()

    return _load_ccswitch_config()


def generate_text(
    prompt: str,
    *,
    instructions: str,
    config: LlmConfig,
) -> str:
    if config.provider == "ollama":
        from langchain_ollama import OllamaLLM

        llm = OllamaLLM(model=config.model)
        combined_prompt = f"{instructions}\n\n{prompt}"
        return str(llm.invoke(combined_prompt)).strip()

    if config.provider == "opencode":
        return _opencode_generate(prompt, instructions, config.model)

    from openai import OpenAI

    client_kwargs: dict[str, str] = {"api_key": _required_value(config.api_key, "缺少 API Key")}
    if config.base_url:
        client_kwargs["base_url"] = config.base_url
    client = OpenAI(**client_kwargs)

    request: dict[str, object] = {
        "model": config.model,
        "instructions": instructions,
        "input": prompt,
        "store": config.store,
    }
    if config.reasoning_effort:
        request["reasoning"] = {"effort": config.reasoning_effort}

    response = client.responses.create(**request)
    output_text = (response.output_text or "").strip()
    if not output_text:
        raise RuntimeError("API 返回成功，但没有可显示的文本。")
    return output_text


def describe_config(config: LlmConfig) -> str:
    if not config.base_url:
        return config.display_name
    host = urlparse(config.base_url).netloc or config.base_url
    return f"{config.display_name} @ {host}"


def _load_ccswitch_config() -> LlmConfig:
    config_path = Path(
        os.getenv("CCSWITCH_CODEX_CONFIG", "~/.codex/config.toml")
    ).expanduser()
    auth_path = Path(
        os.getenv("CCSWITCH_CODEX_AUTH", "~/.codex/auth.json")
    ).expanduser()

    if not config_path.is_file():
        raise ValueError(f"没有找到 CCSwitch/Codex 配置：{config_path}")
    if not auth_path.is_file():
        raise ValueError(f"没有找到 CCSwitch/Codex 认证文件：{auth_path}")

    with config_path.open("rb") as file:
        codex_config = tomllib.load(file)
    with auth_path.open("r", encoding="utf-8") as file:
        auth_config = json.load(file)

    provider_id = str(codex_config.get("model_provider") or "").strip()
    providers = codex_config.get("model_providers") or {}
    provider_config = providers.get(provider_id) or {}
    if not provider_id or not provider_config:
        raise ValueError("CCSwitch 当前 Codex provider 配置不完整。")

    wire_api = str(provider_config.get("wire_api") or "responses").strip().lower()
    if wire_api != "responses":
        raise ValueError(
            f"CCSwitch 当前 provider 使用 wire_api={wire_api}，本项目第一版只支持 responses。"
        )

    api_key = _required_value(
        os.getenv("CCSWITCH_API_KEY") or auth_config.get("OPENAI_API_KEY"),
        "CCSwitch 当前 Codex provider 没有可用的 OPENAI_API_KEY。",
    )
    model = _required_value(
        os.getenv("CCSWITCH_MODEL") or codex_config.get("model"),
        "CCSwitch 当前 Codex provider 没有配置模型。",
    )
    base_url = _required_value(
        os.getenv("CCSWITCH_BASE_URL") or provider_config.get("base_url"),
        "CCSwitch 当前 Codex provider 没有配置 base_url。",
    )
    reasoning_effort = _reasoning_effort(
        os.getenv("CCSWITCH_REASONING_EFFORT")
        or codex_config.get("model_reasoning_effort")
        or "low"
    )
    provider_name = str(provider_config.get("name") or provider_id).strip()
    store = not bool(codex_config.get("disable_response_storage", False))

    return LlmConfig(
        provider="ccswitch",
        model=model,
        display_name=f"CCSwitch / {provider_name} / {model}",
        api_key=api_key,
        base_url=base_url,
        reasoning_effort=reasoning_effort,
        store=store,
    )


def _load_opencode_config() -> LlmConfig:
    opencode = _find_opencode()
    if not opencode:
        raise RuntimeError("没有找到 OpenCode 命令。")
    model = os.getenv("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free").strip()
    return LlmConfig(
        provider="opencode",
        model=model,
        display_name=f"OpenCode / {model}",
    )


def _find_opencode() -> str | None:
    return (
        shutil.which("opencode") or shutil.which("opencode.exe")
    )


def _opencode_generate(prompt: str, instructions: str, model: str) -> str:
    opencode = _find_opencode()
    if not opencode:
        raise RuntimeError("没有找到 OpenCode 命令。")
    project_root = Path(__file__).resolve().parent.parent
    combined = f"{instructions}\n\n{prompt}"
    try:
        result = subprocess.run(
            [opencode, "run", "--pure", "--model", model, "--dir", str(project_root), "--format", "json", combined],
            cwd=project_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("OpenCode 生成超时。") from None

    fragments: list[str] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            if event.get("type") == "text":
                part = event.get("part") or {}
                if part.get("type") == "text" and part.get("text"):
                    fragments.append(part["text"])
        except (json.JSONDecodeError, KeyError):
            continue

    output = "".join(fragments).strip()
    if not output and not result.stdout.lstrip().startswith("{"):
        output = ANSI_PATTERN.sub("", result.stdout).strip()
    if not output:
        stderr = ANSI_PATTERN.sub("", result.stderr).strip()
        raise RuntimeError(f"OpenCode 执行完成但没有返回文本。\n{stderr}" if stderr else "OpenCode 执行完成但没有返回文本。")
    return output


def _required_value(value: object, message: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(message)
    return text


def _optional_value(value: object) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _reasoning_effort(value: object) -> str | None:
    effort = _optional_value(value)
    if effort is None:
        return None
    normalized = effort.lower()
    if normalized not in SUPPORTED_REASONING_EFFORTS:
        supported = ", ".join(sorted(SUPPORTED_REASONING_EFFORTS))
        raise ValueError(f"不支持的 reasoning effort：{effort}。可选值：{supported}")
    return normalized
