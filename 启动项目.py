from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
VENV_PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def ensure_virtual_environment() -> None:
    if not VENV_PYTHON.is_file():
        raise RuntimeError(f"没有找到虚拟环境 Python：{VENV_PYTHON}")

    current = os.path.normcase(str(Path(sys.executable).resolve()))
    expected = os.path.normcase(str(VENV_PYTHON.resolve()))
    if current == expected:
        return

    os.execv(
        str(VENV_PYTHON),
        [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
    )


ensure_virtual_environment()

from cli.llm_provider import describe_config, load_llm_config  # noqa: E402


KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
VECTOR_STORE = KNOWLEDGE_ROOT / "vector_store"
RESEARCH_SKILL = PROJECT_ROOT / ".opencode" / "skills" / "myresearch" / "SKILL.md"
APP_SETTINGS_PATH = PROJECT_ROOT / ".rag-settings.json"
OLLAMA_MODEL = "qwen3:0.6b"
OPENCODE_RESEARCH_MODEL = os.getenv(
    "OPENCODE_RESEARCH_MODEL", "opencode/deepseek-v4-flash-free"
).strip()
SUPPORTED_PROVIDERS = {"ollama", "openai", "ccswitch", "opencode"}
ANSI_PATTERN = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def configure_process() -> None:
    os.chdir(PROJECT_ROOT)
    os.environ["PYTHONUTF8"] = "1"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def find_command(name: str) -> str | None:
    return shutil.which(name) or shutil.which(f"{name}.exe")


def run_command(
    arguments: list[str],
    *,
    capture: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            cwd=PROJECT_ROOT,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        details = "\n".join(
            part.strip()
            for part in (exc.stdout or "", exc.stderr or "")
            if part.strip()
        )
        if len(details) > 3000:
            details = details[-3000:]
        message = f"命令执行失败，退出码 {exc.returncode}"
        if details:
            message = f"{message}：\n{details}"
        raise RuntimeError(message) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"命令执行超时：{' '.join(arguments[:3])}") from exc


def load_saved_settings() -> dict[str, str]:
    if not APP_SETTINGS_PATH.is_file():
        return {"provider": "ollama"}
    try:
        settings = json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            return {"provider": "ollama"}
        provider = str(settings.get("provider") or "").lower()
        if provider not in SUPPORTED_PROVIDERS:
            provider = "ollama"
        return {
            "provider": provider,
            "ollama_model": str(settings.get("ollama_model") or "").strip(),
            "openai_model": str(settings.get("openai_model") or "").strip(),
            "openai_base_url": str(settings.get("openai_base_url") or "").strip(),
            "opencode_model": str(settings.get("opencode_model") or "").strip(),
        }
    except (OSError, json.JSONDecodeError):
        pass
    return {"provider": "ollama"}


def save_settings(settings: dict[str, str]) -> None:
    content = json.dumps(settings, ensure_ascii=False, indent=2)
    APP_SETTINGS_PATH.write_text(content + "\n", encoding="utf-8")


def read_required(prompt: str) -> str:
    value = input(prompt).strip()
    if not value:
        raise ValueError("输入不能为空。")
    return value


def safe_file_name(text: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text.strip())
    value = value.rstrip(" .") or "未命名"
    return value[:40]


class ProjectMenu:
    def __init__(self) -> None:
        self.settings = load_saved_settings()
        self.provider = self.settings["provider"]
        self._apply_saved_settings()
        os.environ["RAG_LLM_PROVIDER"] = self.provider

    def _apply_saved_settings(self) -> None:
        if self.settings.get("ollama_model"):
            os.environ["OLLAMA_MODEL"] = self.settings["ollama_model"]
        if self.settings.get("openai_model"):
            os.environ["OPENAI_MODEL"] = self.settings["openai_model"]
        if self.settings.get("openai_base_url"):
            os.environ["OPENAI_BASE_URL"] = self.settings["openai_base_url"]
        if self.settings.get("opencode_model"):
            os.environ["OPENCODE_MODEL"] = self.settings["opencode_model"]

    def rag_index_exists(self) -> bool:
        return (VECTOR_STORE / "chroma.sqlite3").is_file()

    def ollama_model_exists(self) -> bool:
        ollama = find_command("ollama")
        if not ollama:
            return False
        try:
            result = run_command([ollama, "list"], capture=True, timeout=20)
            model = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL).strip()
            return model.lower() in result.stdout.lower()
        except RuntimeError:
            return False

    def ccswitch_config_exists(self) -> bool:
        try:
            load_llm_config("ccswitch")
            return True
        except Exception:
            return False

    def provider_ready(self) -> bool:
        try:
            load_llm_config(self.provider)
            if self.provider == "ollama":
                return self.ollama_model_exists()
            if self.provider == "opencode":
                return bool(find_command("opencode"))
            return True
        except Exception:
            return False

    def provider_display_name(self) -> str:
        names = {
            "ollama": "Ollama",
            "openai": "OpenAI API",
            "ccswitch": "CCSwitch 当前 Codex Provider",
            "opencode": "OpenCode",
        }
        return names.get(self.provider, self.provider)

    def select_provider(self) -> None:
        print()
        print("1. Ollama（本地）")
        print("2. OpenAI API")
        print("3. CCSwitch 当前 Codex Provider")
        print("4. OpenCode")
        print()
        choice = input("请选择 AI 后端：").strip()
        provider = {"1": "ollama", "2": "openai", "3": "ccswitch", "4": "opencode"}.get(choice)
        if not provider:
            raise ValueError("请输入 1、2、3 或 4。")

        previous_environment = {
            key: os.environ.get(key)
            for key in ("RAG_LLM_PROVIDER", "OLLAMA_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENCODE_MODEL")
        }
        previous = self.provider
        try:
            if provider == "ollama":
                current = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL)
                model = input(f"Ollama 模型（直接回车使用 {current}）：").strip()
                os.environ["OLLAMA_MODEL"] = model or current
            elif provider == "openai":
                if not os.getenv("OPENAI_API_KEY", "").strip():
                    api_key = getpass.getpass("请输入 OpenAI API Key（仅当前会话使用）：").strip()
                    if not api_key:
                        raise ValueError("OpenAI API Key 不能为空。")
                    os.environ["OPENAI_API_KEY"] = api_key
                current_model = os.getenv("OPENAI_MODEL", "gpt-5.6")
                model = input(f"OpenAI 模型（直接回车使用 {current_model}）：").strip()
                os.environ["OPENAI_MODEL"] = model or current_model
                current_base_url = os.getenv("OPENAI_BASE_URL", "")
                base_url = input(
                    f"Base URL（直接回车使用 {'官方 OpenAI' if not current_base_url else current_base_url}）："
                ).strip()
                if base_url:
                    os.environ["OPENAI_BASE_URL"] = base_url
                elif not current_base_url:
                    os.environ.pop("OPENAI_BASE_URL", None)
            elif provider == "opencode":
                if not find_command("opencode"):
                    raise RuntimeError("没有找到 OpenCode 命令，请先安装 OpenCode。")
                current_model = os.getenv("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free")
                model = input(f"OpenCode 模型（直接回车使用 {current_model}）：").strip()
                os.environ["OPENCODE_MODEL"] = model or current_model

            self.provider = provider
            os.environ["RAG_LLM_PROVIDER"] = provider
            summary = describe_config(load_llm_config(provider))
            if provider == "ollama" and not self.ollama_model_exists():
                model = os.getenv("OLLAMA_MODEL", OLLAMA_MODEL)
                raise RuntimeError(f"Ollama 中未找到模型 {model}，请先执行 ollama pull {model}。")
        except Exception:
            self.provider = previous
            for key, value in previous_environment.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            raise

        self.settings.update(
            {
                "provider": provider,
                "ollama_model": os.getenv("OLLAMA_MODEL", ""),
                "openai_model": os.getenv("OPENAI_MODEL", ""),
                "openai_base_url": os.getenv("OPENAI_BASE_URL", ""),
                "opencode_model": os.getenv("OPENCODE_MODEL", ""),
            }
        )
        save_settings(self.settings)
        print(f"\nAI 后端已真实切换：{summary}")
        print("后续调研报告和自由提问将使用该后端；API Key 不会写入项目文件。")

    def remove_vector_store(self) -> None:
        target = VECTOR_STORE.resolve()
        expected = (PROJECT_ROOT / "knowledge" / "vector_store").resolve()
        if target != expected or not target.is_relative_to(PROJECT_ROOT.resolve()):
            raise RuntimeError(f"索引路径校验失败：{target}")
        if target.exists():
            shutil.rmtree(target)

    def keyword_research(self) -> None:
        request = read_required("请输入调研内容：")
        download = input("是否下载论文 PDF？（y/n，默认 y）：").strip().lower()
        download_papers = download != "n"
        from cli.researcher import conduct_research

        conduct_research(request, download_papers=download_papers)
        print("需要让 RAG 使用新内容时，请再执行菜单 2。")

    def build_rag_index(self) -> None:
        started_at = time.perf_counter()
        print("\n[过程 1/3] 校验并清理旧的向量索引...")
        self.remove_vector_store()
        print("[过程 2/3] 扫描 knowledge 下的 Markdown、TXT 和 PDF，加载并分块...")
        run_command([sys.executable, "-m", "indexer.build_index"])
        elapsed = time.perf_counter() - started_at
        print(f"[过程 3/3] 向量索引已写入：{VECTOR_STORE}")
        print(f"RAG 索引处理完成，耗时 {elapsed:.1f} 秒。")

    def research_report(self) -> None:
        if not self.rag_index_exists():
            raise RuntimeError("RAG 索引尚未建立，请先执行菜单 2。")
        if not self.provider_ready():
            raise RuntimeError(
                f"当前 AI 后端不可用：{self.provider_display_name()}。请执行菜单 5 重新配置。"
            )

        request = read_required("请输入报告要求：")
        report_prompt = (
            "请仅根据知识库内容，按照下面的要求生成一份中文调研报告：\n\n"
            f"{request}\n\n"
            "报告使用 Markdown，至少包含标题、摘要、主要发现、对比或分析、结论。"
            "知识库没有的信息请明确说明不知道，不要编造。"
        )
        started_at = time.perf_counter()
        print("\n[过程 1/4] 已确认 RAG 索引和 AI 后端可用。")
        print("[过程 2/4] 将用户要求转换为：仅使用知识库、Markdown 输出、信息不足时明确说明。")
        print(f"[过程 3/4] 调用 {self.provider_display_name()} 检索知识库并生成报告...")
        result = run_command(
            [
                sys.executable,
                "-m",
                "cli.main",
                report_prompt,
                "--verbose",
                "--trace",
                "--provider",
                self.provider,
            ],
            capture=True,
        )
        report_output = result.stdout.strip()
        if result.stderr.strip():
            print(result.stderr.strip())

        output_directory = KNOWLEDGE_ROOT / "reports"
        output_directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_directory / f"报告_{safe_file_name(request)}_{timestamp}.md"
        document = (
            "# 调研报告\n\n"
            f"- 生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n"
            f"- 用户要求：{request}\n\n"
            f"{report_output}\n"
        )
        output_path.write_text(document, encoding="utf-8")
        print(f"[过程 4/4] 报告已保存：{output_path}")
        print(f"生成完成，耗时 {time.perf_counter() - started_at:.1f} 秒。\n")
        print(report_output)

    def free_question(self) -> None:
        if not self.rag_index_exists():
            raise RuntimeError("RAG 索引尚未建立，请先执行菜单 2。")
        if not self.provider_ready():
            raise RuntimeError(
                f"当前 AI 后端不可用：{self.provider_display_name()}。请执行菜单 5 重新配置。"
            )
        question = read_required("请输入问题：")
        print("\n[过程 1/3] 已确认 RAG 索引和 AI 后端可用。")
        print(f"[过程 2/3] 根据问题检索知识库，并让 {self.provider_display_name()} 生成回答。")
        print("[过程 3/3] 输出回答、参考来源和后端信息。\n")
        run_command(
            [
                sys.executable,
                "-m",
                "cli.main",
                question,
                "--verbose",
                "--trace",
                "--provider",
                self.provider,
            ]
        )

    def self_test(self) -> None:
        checks = {
            "ProjectRoot": str(PROJECT_ROOT),
            "Python": sys.version.split()[0],
            "VenvPython": os.path.normcase(str(Path(sys.executable).resolve()))
            == os.path.normcase(str(VENV_PYTHON.resolve())),
            "OpenCodeCommand": bool(find_command("opencode")),
            "OpenCodeModel": OPENCODE_RESEARCH_MODEL,
            "ResearchSkill": RESEARCH_SKILL.is_file(),
            "RagIndex": self.rag_index_exists(),
            "OllamaModel": self.ollama_model_exists(),
            "AiProvider": self.provider,
            "AiProviderReady": self.provider_ready(),
            "CCSwitchConfig": self.ccswitch_config_exists(),
        }
        width = max(len(key) for key in checks)
        for key, value in checks.items():
            print(f"{key:<{width}} : {value}")

    def show_menu(self) -> None:
        while True:
            if sys.stdout.isatty():
                print("\033[2J\033[H", end="")
            index_status = "已建立" if self.rag_index_exists() else "未建立"
            provider_status = "可用" if self.provider_ready() else "不可用"

            print("========================================")
            print("        个人知识库助手")
            print("========================================")
            print(f"RAG 索引：{index_status}")
            print(f"AI 后端：{self.provider_display_name()}（{provider_status}）")
            print()
            print("1. 输入调研内容，自动搜索网络并分类保存到 knowledge")
            print("2. 执行 RAG 索引")
            print("3. 根据提示词生成调研报告")
            print("4. 自由提问")
            print("5. 切换 AI 后端（Ollama / OpenAI / CCSwitch / OpenCode）")
            print("0. 退出")
            print()

            try:
                choice = input("请选择：").strip()
            except EOFError:
                return
            if choice == "0":
                return

            try:
                actions = {
                    "1": self.keyword_research,
                    "2": self.build_rag_index,
                    "3": self.research_report,
                    "4": self.free_question,
                    "5": self.select_provider,
                }
                action = actions.get(choice)
                if not action:
                    print("请输入 0 到 5。")
                else:
                    action()
            except (RuntimeError, ValueError, OSError) as exc:
                print(f"\n操作失败：{exc}")
            except KeyboardInterrupt:
                print("\n操作已取消。")

            print()
            try:
                input("按 Enter 返回主菜单")
            except EOFError:
                return


def main() -> int:
    parser = argparse.ArgumentParser(description="个人知识库助手启动菜单")
    parser.add_argument("--self-test", action="store_true", help="执行非交互环境检查")
    args = parser.parse_args()

    configure_process()
    menu = ProjectMenu()
    if args.self_test:
        menu.self_test()
    else:
        menu.show_menu()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\n启动失败：{exc}")
        if sys.stdin.isatty():
            input("按 Enter 关闭")
        raise
