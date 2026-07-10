from typing import Optional

import typer

from cli.llm_provider import describe_config, generate_text, load_llm_config


app = typer.Typer()


@app.command()
def generate(
    prompt: str,
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="AI 后端：ollama、openai 或 ccswitch。",
    ),
):
    try:
        config = load_llm_config(provider)
        result = generate_text(
            prompt,
            instructions="你是调研与写作助手。严格遵守用户要求，信息不足时明确说明。",
            config=config,
        )
    except Exception as exc:
        typer.echo(f"生成失败：{exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(result)
    typer.echo(f"\n[AI 后端：{describe_config(config)}]", err=True)


if __name__ == "__main__":
    app()
