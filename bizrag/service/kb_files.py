from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".docx",
    ".doc",
    ".wps",
    ".pdf",
    ".xps",
    ".oxps",
    ".epub",
    ".mobi",
    ".fb2",
}
EXCEL_EXTENSIONS = {".xls", ".xlsx"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | EXCEL_EXTENSIONS
IGNORED_PREFIXES = {"~$"}


def classify_source_type(path: Path) -> Optional[str]:
    suffix = path.suffix.lower()
    if suffix in EXCEL_EXTENSIONS:
        return "excel"
    if suffix in TEXT_EXTENSIONS:
        return suffix.lstrip(".")
    return None


def normalize_source_uri(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.scheme != "file":
        return value
    if parsed.scheme == "file":
        return str(Path(parsed.path).resolve())
    return str(Path(value).resolve())


def should_ingest(path: Path) -> bool:
    if any(path.name.startswith(prefix) for prefix in IGNORED_PREFIXES):
        return False
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def discover_supported_files(path: Path) -> List[Path]:
    if path.is_file():
        return [path] if should_ingest(path) else []

    files: List[Path] = []
    for file_path in sorted(path.rglob("*")):
        if file_path.is_file() and should_ingest(file_path):
            files.append(file_path.resolve())
    return files
