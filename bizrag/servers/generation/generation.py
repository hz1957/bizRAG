from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ultrarag.server import UltraRAG_MCP_Server

app = UltraRAG_MCP_Server("generation")

_state: Dict[str, Any] = {
    "backend": None,
    "client": None,
    "model_name": None,
    "sampling_params": {},
    "extra_params": {},
}


def _coerce_prompt(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, dict):
        if isinstance(prompt.get("content"), str):
            return prompt["content"]
        if isinstance(prompt.get("content"), dict):
            text = prompt["content"].get("text")
            if text is not None:
                return str(text)
        if prompt.get("text") is not None:
            return str(prompt["text"])
    return str(prompt)


def _cfg_or_env(cfg: Dict[str, Any], key: str, *env_names: str) -> str:
    value = str(cfg.get(key) or "").strip()
    if value:
        return value
    for env_name in env_names:
        value = str(os.environ.get(env_name) or "").strip()
        if value:
            return value
    return ""


@app.tool(output="backend_configs,sampling_params,extra_params,backend->None")
def generation_init(
    backend_configs: Dict[str, Any],
    sampling_params: Dict[str, Any],
    extra_params: Optional[Dict[str, Any]] = None,
    backend: str = "openai",
) -> None:
    backend_name = str(backend or "openai").lower()
    if backend_name != "openai":
        raise ValueError(f"[generation] unsupported backend: {backend_name}")

    cfg = dict((backend_configs or {}).get("openai") or {})
    model_name = _cfg_or_env(cfg, "model_name", "LLM_MODEL_NAME", "OPENAI_MODEL_NAME")
    base_url = _cfg_or_env(cfg, "base_url", "LLM_API_URL_AGENT", "OPENAI_BASE_URL")
    api_key = _cfg_or_env(cfg, "api_key", "LLM_API_KEY_AGENT", "OPENAI_API_KEY")

    if not model_name:
        raise ValueError("[generation] openai.model_name is required")
    if not base_url:
        raise ValueError("[generation] openai.base_url is required")
    if not api_key:
        raise ValueError("[generation] openai.api_key is required")

    _state["backend"] = backend_name
    _state["client"] = OpenAI(base_url=base_url, api_key=api_key)
    _state["model_name"] = model_name
    _state["sampling_params"] = dict(sampling_params or {})
    _state["extra_params"] = dict(extra_params or {})


@app.tool(output="prompt_ls,system_prompt->ans_ls")
def generate(
    prompt_ls: List[Any],
    system_prompt: str = "",
) -> Dict[str, List[str]]:
    if _state["backend"] != "openai" or _state["client"] is None:
        raise RuntimeError("[generation] generation_init must be called first")

    client: OpenAI = _state["client"]
    model_name = str(_state["model_name"])
    sampling_params = dict(_state["sampling_params"] or {})
    extra_params = dict(_state["extra_params"] or {})

    answers: List[str] = []
    for prompt in prompt_ls:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": _coerce_prompt(prompt)})

        request_kwargs = dict(sampling_params)
        if extra_params:
            request_kwargs["extra_body"] = extra_params

        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            **request_kwargs,
        )
        content = response.choices[0].message.content or ""
        answers.append(str(content))

    return {"ans_ls": answers}


if __name__ == "__main__":
    app.run(transport="stdio")
