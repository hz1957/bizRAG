from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from bizrag.common.io_utils import load_yaml

SERVER_PARAMETER_FILES = {
    "benchmark": "servers/benchmark/parameter.yaml",
    "retriever": "servers/retriever/parameter.yaml",
    "reranker": "servers/reranker/parameter.yaml",
    "merge": "servers/custom/parameter.yaml",
    "prompt": "servers/prompt/parameter.yaml",
    "generation": "servers/generation/parameter.yaml",
    "evaluation": "servers/evaluation/parameter.yaml",
}


def deep_merge_dicts(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


@lru_cache(maxsize=1)
def _default_server_parameters() -> Dict[str, Any]:
    bizrag_root = Path(__file__).resolve().parents[2]
    defaults: Dict[str, Any] = {}
    for section, relative_path in SERVER_PARAMETER_FILES.items():
        defaults[section] = load_yaml(bizrag_root / relative_path)
    return defaults


def normalize_server_parameters(cfg: Dict[str, Any]) -> Dict[str, Any]:
    data = deepcopy(cfg or {})

    if isinstance(data.get("retriever"), dict):
        normalized = data
    else:
        retriever_cfg = {
            key: deepcopy(value)
            for key, value in data.items()
            if key
            not in {
                "benchmark",
                "reranker",
                "merge",
                "prompt",
                "generation",
                "evaluation",
                "base_config",
            }
        }
        normalized = {
            "retriever": retriever_cfg,
            "benchmark": deepcopy(data.get("benchmark") or {}),
            "reranker": deepcopy(data.get("reranker") or {}),
            "merge": deepcopy(data.get("merge") or {}),
            "prompt": deepcopy(data.get("prompt") or {}),
            "generation": deepcopy(data.get("generation") or {}),
            "evaluation": deepcopy(data.get("evaluation") or {}),
        }

    normalized.setdefault("retriever", {})
    normalized.setdefault("benchmark", {})
    normalized.setdefault("reranker", {})
    normalized.setdefault("merge", {})
    normalized.setdefault("prompt", {})
    normalized.setdefault("generation", {})
    normalized.setdefault("evaluation", {})
    return normalized


def merge_with_default_server_parameters(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return deep_merge_dicts(_default_server_parameters(), normalize_server_parameters(cfg))


def default_server_parameters() -> Dict[str, Any]:
    return deepcopy(_default_server_parameters())


_NO_OVERRIDE = object()


def extract_override_dict(base: Any, target: Any) -> Any:
    if isinstance(base, dict) and isinstance(target, dict):
        override: Dict[str, Any] = {}
        for key, target_value in target.items():
            if key not in base or base[key] != target_value:
                override[key] = deepcopy(target_value)
        return override if override else _NO_OVERRIDE
    if base == target:
        return _NO_OVERRIDE
    return deepcopy(target)


def _load_server_parameter_override(path: Path, visited: set[Path]) -> Dict[str, Any]:
    resolved_path = path.resolve()
    if resolved_path in visited:
        chain = " -> ".join(str(item) for item in [*visited, resolved_path])
        raise RuntimeError(f"Circular server parameter base_config chain: {chain}")

    visited.add(resolved_path)
    try:
        data = load_yaml(resolved_path)
        base_ref = data.pop("base_config", None)
        if not base_ref:
            return data

        base_path = Path(str(base_ref))
        if not base_path.is_absolute():
            config_relative_base_path = resolved_path.parent / base_path
            if config_relative_base_path.exists():
                base_path = config_relative_base_path
        base_cfg = _load_server_parameter_override(base_path, visited)
        return deep_merge_dicts(base_cfg, data)
    finally:
        visited.remove(resolved_path)


def load_server_parameters(path: str | Path) -> Dict[str, Any]:
    override_cfg = _load_server_parameter_override(Path(path), visited=set())
    return merge_with_default_server_parameters(override_cfg)
