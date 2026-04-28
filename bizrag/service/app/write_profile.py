from __future__ import annotations

import re
from typing import Any, Dict
from pathlib import Path

from bizrag.common.chunk_defaults import current_chunk_settings

_SAP_PATTERNS = (
    re.compile(r"(^|[\W_])sap([\W_]|$)", re.IGNORECASE),
    re.compile(r"statistical[\s._-]*analysis[\s._-]*plan", re.IGNORECASE),
    re.compile(r"统计分析计划"),
    re.compile(r"统计分析方案"),
)
_PROTOCOL_PATTERNS = (
    re.compile(r"\bstudy[\s._-]*protocol\b", re.IGNORECASE),
    re.compile(r"(^|[\W_])protocol([\W_]|$)", re.IGNORECASE),
    re.compile(r"研究方案"),
    re.compile(r"临床试验方案"),
)


def _base_profile(name: str) -> Dict[str, Any]:
    settings = current_chunk_settings()
    return {
        "name": name,
        "chunk_backend": settings["chunk_backend"],
        "chunk_size": int(settings["chunk_size"]),
        "chunk_overlap": int(settings["chunk_overlap"]),
        "tokenizer_or_token_counter": settings["tokenizer_or_token_counter"],
        "use_title": True,
        "prefer_mineru": False,
    }


def _matches_any(patterns: tuple[re.Pattern[str], ...], value: str) -> bool:
    return any(pattern.search(value) for pattern in patterns)


def select_write_profile(
    *,
    file_name: str,
    file_path: Path,
    prefer_mineru: bool = False,
) -> Dict[str, Any]:
    normalized_name = str(file_name or file_path.name)

    if _matches_any(_SAP_PATTERNS, normalized_name):
        profile = _base_profile("sap")
        profile["chunk_size"] = 1200
        profile["chunk_overlap"] = 240
    elif _matches_any(_PROTOCOL_PATTERNS, normalized_name):
        profile = _base_profile("protocol")
        profile["chunk_size"] = 840
        profile["chunk_overlap"] = 160
    else:
        profile = _base_profile("default")

    if file_path.suffix.lower() == ".pdf":
        profile["prefer_mineru"] = True

    if prefer_mineru:
        profile["prefer_mineru"] = True

    return profile
