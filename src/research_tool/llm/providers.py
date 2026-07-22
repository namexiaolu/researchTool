from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from research_tool.llm.models import GenerationResult, HealthStatus, LlmConfig
from research_tool.shared.errors import ConfigurationError, ProviderError
from research_tool.shared.settings import SUPPORTED_PROTOCOLS, AppSettings, ProviderProfile

ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
SUPPORTED_PROVIDERS = set(SUPPORTED_PROTOCOLS)


@dataclass
class OllamaProvider:
    config: LlmConfig

    @property
    def name(self) -> str:
        return self.config.profile

    async def generate(self, prompt: str, *, instructions: str) -> GenerationResult:
        try:
            from langchain_ollama import OllamaLLM

            if self.config.base_url:
                model = OllamaLLM(model=self.config.model, base_url=self.config.base_url)
            else:
                model = OllamaLLM(model=self.config.model)
            output = str(await model.ainvoke(f"{instructions}\n\n{prompt}")).strip()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ProviderError(f"Ollama 生成失败：{exc}") from exc
        if not output:
            raise ProviderError("Ollama 没有返回文本。")
        return GenerationResult(output)

    def health_check(self, *, live: bool = False) -> HealthStatus:
        if not live:
            return HealthStatus(self.name, bool(self.config.model), f"已配置 {self.config.model}")
        base_url = self.config.base_url or "http://127.0.0.1:11434"
        try:
            response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5)
            response.raise_for_status()
            models = {item.get("name", "") for item in response.json().get("models", [])}
            ready = any(
                name == self.config.model or name.startswith(f"{self.config.model}:")
                for name in models
            )
            message = "模型可用" if ready else f"未找到模型 {self.config.model}"
            return HealthStatus(self.name, ready, message)
        except Exception as exc:
            return HealthStatus(self.name, False, f"Ollama 不可用：{exc}")

    def describe(self) -> str:
        return self.config.display_name


@dataclass
class OpenAIResponsesProvider:
    config: LlmConfig

    @property
    def name(self) -> str:
        return self.config.profile

    async def generate(self, prompt: str, *, instructions: str) -> GenerationResult:
        try:
            from openai import AsyncOpenAI

            client: Any = AsyncOpenAI(
                api_key=_required(self.config.api_key, "缺少 API Key"),
                base_url=self.config.base_url,
                timeout=None,
                max_retries=0,
            )
            request: dict[str, object] = {
                "model": self.config.model,
                "instructions": instructions,
                "input": prompt,
                "store": self.config.store,
            }
            if self.config.reasoning_effort:
                request["reasoning"] = {
                    "effort": self.config.reasoning_effort,
                    "summary": "auto",
                }
            response = await client.responses.create(**request)
            output = (response.output_text or "").strip()
            summaries = _openai_reasoning_summaries(response)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ProviderError(f"{self.config.display_name} 生成失败：{exc}") from exc
        if not output:
            raise ProviderError(f"{self.config.display_name} 没有返回文本。")
        return GenerationResult(output, summaries)

    def health_check(self, *, live: bool = False) -> HealthStatus:
        if not live:
            return HealthStatus(self.name, bool(self.config.api_key), "配置完整，连接未验证")
        base_url = (self.config.base_url or "https://api.openai.com/v1").rstrip("/")
        try:
            response = httpx.get(
                f"{base_url}/models",
                headers={"Authorization": f"Bearer {self.config.api_key}"},
                timeout=5,
            )
            response.raise_for_status()
            return HealthStatus(self.name, True, "连接成功")
        except Exception as exc:
            return HealthStatus(self.name, False, f"连接失败：{exc}")

    def describe(self) -> str:
        return _description(self.config)


@dataclass
class AnthropicMessagesProvider:
    config: LlmConfig

    @property
    def name(self) -> str:
        return self.config.profile

    async def generate(self, prompt: str, *, instructions: str) -> GenerationResult:
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        api_key = _required(self.config.api_key, "缺少 API Key")
        if self.config.auth_mode == "bearer":
            headers["authorization"] = f"Bearer {api_key}"
        else:
            headers["x-api-key"] = api_key
        payload = {
            "model": self.config.model,
            "max_tokens": 8192,
            "system": instructions,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                response = await client.post(
                    _anthropic_messages_url(self.config), headers=headers, json=payload
                )
                response.raise_for_status()
                data = response.json()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise ProviderError(f"{self.config.display_name} 生成失败：{exc}") from exc
        content = data.get("content") if isinstance(data, dict) else None
        blocks = content if isinstance(content, list) else []
        output = "\n".join(
            str(block.get("text", "")).strip()
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text")
        ).strip()
        summaries = tuple(
            str(block.get("text", "")).strip()
            for block in blocks
            if isinstance(block, dict)
            and block.get("type") == "reasoning_summary"
            and block.get("text")
        )
        if not output:
            raise ProviderError(f"{self.config.display_name} 没有返回文本。")
        return GenerationResult(output, summaries)

    def health_check(self, *, live: bool = False) -> HealthStatus:
        message = "配置完整，连接未验证"
        if live:
            message = "Anthropic Messages 不执行无生成连通检查"
        return HealthStatus(self.name, bool(self.config.api_key), message)

    def describe(self) -> str:
        return _description(self.config)


@dataclass
class OpenCodeProvider:
    config: LlmConfig
    executable: str
    project_root: Path

    @property
    def name(self) -> str:
        return self.config.profile

    async def generate(self, prompt: str, *, instructions: str) -> GenerationResult:
        combined = f"{instructions}\n\n{prompt}"
        process = await asyncio.create_subprocess_exec(
            self.executable,
            "run",
            "--pure",
            "--model",
            self.config.model,
            "--dir",
            str(self.project_root),
            "--format",
            "json",
            combined,
            cwd=self.project_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.CancelledError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                process.kill()
                await process.wait()
            raise

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        fragments: list[str] = []
        summaries: list[str] = []
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            part = event.get("part")
            if event.get("type") == "text" and isinstance(part, dict) and part.get("text"):
                fragments.append(str(part["text"]))
            if event.get("type") == "reasoning_summary" and isinstance(part, dict):
                summary = str(part.get("text") or "").strip()
                if summary:
                    summaries.append(summary)

        output = "".join(fragments).strip()
        if not output and not stdout.lstrip().startswith("{"):
            output = ANSI_PATTERN.sub("", stdout).strip()
        if process.returncode != 0 or not output:
            detail = ANSI_PATTERN.sub("", stderr).strip() or f"进程退出码 {process.returncode}"
            raise ProviderError(f"OpenCode 没有返回可用文本：{detail}")
        return GenerationResult(output, tuple(summaries))

    def health_check(self, *, live: bool = False) -> HealthStatus:
        return HealthStatus(self.name, Path(self.executable).is_file(), f"命令：{self.executable}")

    def describe(self) -> str:
        return self.config.display_name


Provider = OllamaProvider | OpenAIResponsesProvider | AnthropicMessagesProvider | OpenCodeProvider


class ProviderFactory:
    def __init__(self, settings: AppSettings, project_root: Path) -> None:
        self.settings = settings
        self.project_root = project_root

    def create(self, profile_name: str | None = None) -> Provider:
        selected = (profile_name or self.settings.active_provider).strip()
        profile = self.settings.profiles.get(selected)
        if profile is None:
            allowed = ", ".join(sorted(self.settings.profiles))
            raise ConfigurationError(f"Provider 档案不存在：{selected}。可选值：{allowed}")
        config = _llm_config(selected, profile)
        if profile.protocol == "ollama":
            return OllamaProvider(config)
        if profile.protocol == "openai-responses":
            return OpenAIResponsesProvider(config)
        if profile.protocol == "anthropic-messages":
            return AnthropicMessagesProvider(config)
        return self._opencode_provider(config)

    def _opencode_provider(self, config: LlmConfig) -> OpenCodeProvider:
        executable = shutil.which("opencode") or shutil.which("opencode.exe")
        if not executable:
            raise ConfigurationError("没有找到 OpenCode 命令；请先配置本机 OpenCode 环境。")
        return OpenCodeProvider(config, executable, self.project_root)


def _llm_config(name: str, profile: ProviderProfile) -> LlmConfig:
    label = {
        "ollama": "Ollama",
        "openai-responses": "OpenAI Responses",
        "anthropic-messages": "Anthropic Messages",
        "opencode": "OpenCode",
    }[profile.protocol]
    return LlmConfig(
        profile=name,
        protocol=profile.protocol,
        model=profile.model,
        display_name=f"{name} / {label} / {profile.model}",
        api_key=profile.api_key or None,
        base_url=profile.base_url or None,
        reasoning_effort=profile.reasoning_effort or None,
        auth_mode=profile.auth_mode,
        store=profile.store,
    )


def _openai_reasoning_summaries(response: object) -> tuple[str, ...]:
    summaries: list[str] = []
    for item in getattr(response, "output", ()) or ():
        for part in getattr(item, "summary", ()) or ():
            text = str(getattr(part, "text", "")).strip()
            if text:
                summaries.append(text)
    return tuple(summaries)


def _anthropic_messages_url(config: LlmConfig) -> str:
    base_url = (config.base_url or "https://api.anthropic.com").rstrip("/")
    return f"{base_url}/messages" if base_url.endswith("/v1") else f"{base_url}/v1/messages"


def _description(config: LlmConfig) -> str:
    if not config.base_url:
        return config.display_name
    host = urlparse(config.base_url).netloc or config.base_url
    return f"{config.display_name} @ {host}"


def _required(value: object, message: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ConfigurationError(message)
    return text
