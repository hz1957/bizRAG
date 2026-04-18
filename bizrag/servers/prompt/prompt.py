from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Template
from ultrarag.server import UltraRAG_MCP_Server

app = UltraRAG_MCP_Server("prompt")


def _load_template(template_path: str) -> Template:
    path = Path(template_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"[prompt] template not found: {template_path}")
    return Template(path.read_text(encoding="utf-8"))


def _stringify_passage(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        title = str(item.get("title") or item.get("file_name") or "").strip()
        content = str(item.get("content") or item.get("contents") or "").strip()
        if title:
            return f"Title: {title}\n{content}".strip()
        return content
    return str(item)


def _normalize_ret_psg_rows(ret_psg: Any, question_count: int) -> List[List[Any]]:
    if ret_psg is None:
        return [[] for _ in range(question_count)]
    if not isinstance(ret_psg, list):
        return [[ret_psg]]
    if not ret_psg:
        return [[] for _ in range(question_count)]
    if isinstance(ret_psg[0], list):
        return ret_psg
    if question_count == 1:
        return [ret_psg]
    raise ValueError("[prompt] ret_psg must be list[list[Any]] for multi-query input")


def _normalize_queries(q_ls: Any) -> List[str]:
    if q_ls is None:
        return []
    if isinstance(q_ls, str):
        return [q_ls]
    if isinstance(q_ls, list):
        return [str(item) for item in q_ls]
    return [str(q_ls)]


@app.tool(output="q_ls,ret_psg,template->prompt_ls")
def qa_rag_boxed(
    q_ls: List[str],
    ret_psg: List[List[Any]],
    template: str,
) -> Dict[str, List[str]]:
    normalized_queries = _normalize_queries(q_ls)
    normalized_ret_psg = _normalize_ret_psg_rows(ret_psg, len(normalized_queries))
    if len(normalized_queries) != len(normalized_ret_psg):
        app.logger.error(
            "[prompt] q_ls/ret_psg mismatch: q_type=%s q_len=%s ret_type=%s ret_len=%s",
            type(q_ls).__name__,
            len(normalized_queries),
            type(ret_psg).__name__,
            len(normalized_ret_psg),
        )
        raise ValueError("[prompt] q_ls and ret_psg must have same length")

    prompt_template = _load_template(template)
    prompts: List[str] = []
    for question, passages in zip(normalized_queries, normalized_ret_psg):
        documents = "\n\n".join(_stringify_passage(item) for item in passages if item)
        prompts.append(
            prompt_template.render(
                question=str(question),
                documents=documents,
            )
        )
    return {"prompt_ls": prompts}


if __name__ == "__main__":
    app.run(transport="stdio")
