import sys
from typing import Optional

import typer
from rich import print as rprint

from cli.llm_provider import describe_config, generate_text, load_llm_config
from indexer.store import get_retriever

app = typer.Typer()
NON_ANSWERS = ("请提供", "请提出", "请说你的问题", "没有提供问题", "还没有提供问题", "我会尽力回答", "请告诉我", "我可以回答")


def retrieve_context(question: str, top_k: int = 5):
    retriever = get_retriever(top_k)
    docs = retriever.invoke(question)
    context = "\n\n".join(
        f"[来源：{doc.metadata.get('source')}]\n{doc.page_content}" for doc in docs
    )
    return docs, context


@app.command()
def ask(
    question: str,
    verbose: bool = False,
    trace: bool = typer.Option(False, "--trace", help="显示可解释的执行阶段，不显示模型隐藏思维链。"),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="AI 后端：ollama、openai 或 ccswitch。",
    ),
    top_k: int = typer.Option(5, min=1, max=20, help="检索文本块数量。"),
):
    try:
        if trace:
            rprint("[dim][过程] 加载 AI 后端配置...[/]", file=sys.stderr)
        config = load_llm_config(provider)
        if trace:
            rprint(f"[dim][过程] 检索知识库，目标文本块数量：{top_k}...[/]", file=sys.stderr)
        docs, context = retrieve_context(question, top_k)
        if trace:
            rprint(f"[dim][过程] 已检索到 {len(docs)} 个参考文本块。[/]", file=sys.stderr)
        prompt = f"资料：\n{context}\n\n问题：{question}\n请直接回答问题。"
        if trace:
            rprint("[dim][过程] 组装上下文和回答约束，开始调用模型...[/]", file=sys.stderr)
        answer = generate_text(
            prompt,
            instructions="回答问题。",
            config=config,
        )
        if len(answer) < 30 or any(text in answer for text in NON_ANSWERS):
            answer = f"模型未给出有效回答，以下是最相关的知识库资料：\n\n{docs[0].page_content}"
        if trace:
            rprint(f"[dim][过程] 模型已返回回答，共 {len(answer):,} 个字符。[/]", file=sys.stderr)
    except Exception as exc:
        rprint(f"[bold red]问答失败[/]：{exc}")
        raise typer.Exit(code=1) from exc

    rprint(f"\n[bold cyan]回答[/]：\n{answer}\n")
    if verbose:
        rprint("[dim]--- 参考来源 ---[/]")
        for i, d in enumerate(docs, 1):
            rprint(f"{i}. {d.metadata.get('source')}")
        rprint(f"[dim]AI 后端：{describe_config(config)}[/]")

if __name__ == "__main__":
    app()
