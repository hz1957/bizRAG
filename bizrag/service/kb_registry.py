from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from bizrag.service.io_utils import load_yaml


class KBRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.mapping: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self.mapping = {}
            return
        data = load_yaml(self.path)
        self.mapping = data.get("mappings", data)

    def resolve(self, kb_id: str) -> str:
        if not kb_id:
            raise ValueError("kb_id is required")
        mapped = self.mapping.get(kb_id)
        if isinstance(mapped, dict):
            collection_name = mapped.get("collection_name")
            if collection_name:
                return str(collection_name)
        elif isinstance(mapped, str) and mapped.strip():
            return mapped.strip()
        return kb_id
