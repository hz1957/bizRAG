from __future__ import annotations

import io
from pathlib import Path
from typing import BinaryIO

from .config import Settings


def _safe_name(name: str) -> str:
    name = Path(name).name
    if not name:
        return "file"
    return "".join(ch if ch.isalnum() or ch in {"-", "_", ".", " ", "+"} else "_" for ch in name).strip()


class LocalFileStorage:
    def __init__(self, settings: Settings) -> None:
        self._root = Path(settings.storage_root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _build_path(self, tenant_id: str, file_id: str, version: str, file_name: str | None) -> Path:
        filename = _safe_name(file_name or "file")
        return self._root / tenant_id / file_id / version / filename

    def save(
        self,
        *,
        tenant_id: str,
        file_id: str,
        version: str,
        file_name: str | None,
        source: BinaryIO,
    ) -> tuple[str, int]:
        target = self._build_path(tenant_id=tenant_id, file_id=file_id, version=version, file_name=file_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with target.open("wb") as out:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                total += len(chunk)
        return str(target.relative_to(self._root)), total

    def save_bytes(
        self,
        *,
        tenant_id: str,
        file_id: str,
        version: str,
        file_name: str | None,
        data: bytes,
    ) -> tuple[str, int]:
        with io.BytesIO(data) as buffer:
            return self.save(
                tenant_id=tenant_id,
                file_id=file_id,
                version=version,
                file_name=file_name,
                source=buffer,
            )

    def resolve(self, storage_key: str) -> Path:
        return self._root / storage_key

    def read_bytes(self, storage_key: str) -> bytes:
        return self.resolve(storage_key).read_bytes()

    def delete(self, storage_key: str) -> None:
        path = self.resolve(storage_key)
        if path.exists():
            path.unlink()
            if path.parent.exists():
                try:
                    path.parent.rmdir()
                except OSError:
                    pass
