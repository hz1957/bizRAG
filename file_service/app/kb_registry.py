from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import Settings


logger = logging.getLogger(__name__)


class KBAutoRegistrar:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._known_kb_ids: set[str] = set()
        self._known_deleted_kb_ids: set[str] = set()

    def ensure_registered(self, kb_id: str) -> None:
        normalized_kb_id = str(kb_id or "").strip()
        if not normalized_kb_id or normalized_kb_id in self._known_kb_ids:
            return
        if not self._settings.watch_auto_register_enabled:
            return
        register_url = str(self._settings.watch_auto_register_url or "").strip()
        source_parameters_path = str(self._settings.watch_auto_register_source_parameters_path or "").strip()
        if not register_url or not source_parameters_path:
            raise RuntimeError(
                "watch auto-register requires FILE_SERVICE_WATCH_AUTO_REGISTER_URL "
                "and FILE_SERVICE_WATCH_AUTO_REGISTER_SOURCE_PARAMETERS_PATH"
            )
        payload: dict[str, Any] = {
            "kb_id": normalized_kb_id,
            "collection_name": normalized_kb_id,
            "display_name": normalized_kb_id,
            "source_parameters_path": source_parameters_path,
        }
        source_root_prefix = str(self._settings.watch_auto_register_source_root_prefix or "").strip()
        if source_root_prefix:
            payload["source_root"] = str(Path(source_root_prefix) / normalized_kb_id)

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            register_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._settings.watch_auto_register_timeout_seconds) as response:
                response.read()
                logger.info("auto-registered kb_id=%s via watcher", normalized_kb_id)
        except TimeoutError as exc:
            raise RuntimeError(f"auto-register kb_id={normalized_kb_id} timed out") from exc
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            raise RuntimeError(
                f"auto-register kb_id={normalized_kb_id} failed with HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"auto-register kb_id={normalized_kb_id} failed: {exc}") from exc
        self._known_kb_ids.add(normalized_kb_id)
        self._known_deleted_kb_ids.discard(normalized_kb_id)

    def ensure_deleted(self, kb_id: str, *, force: bool = True) -> None:
        normalized_kb_id = str(kb_id or "").strip()
        if not normalized_kb_id or normalized_kb_id in self._known_deleted_kb_ids:
            return
        register_url = str(self._settings.watch_auto_register_url or "").strip()
        if not register_url:
            return

        delete_url = register_url.rstrip("/")
        if delete_url.endswith("/register"):
            delete_url = delete_url[: -len("/register")]
        delete_url = f"{delete_url}/{quote(normalized_kb_id, safe='')}"
        if force:
            delete_url = f"{delete_url}?force=true"

        request = Request(delete_url, method="DELETE")
        try:
            with urlopen(request, timeout=self._settings.watch_auto_register_timeout_seconds) as response:
                response.read()
                logger.info("auto-deleted kb_id=%s via watcher", normalized_kb_id)
        except TimeoutError as exc:
            raise RuntimeError(f"auto-delete kb_id={normalized_kb_id} timed out") from exc
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore").strip()
            if exc.code == 404 or (
                exc.code == 400 and "unknown kb_id" in detail.lower()
            ):
                logger.info("auto-delete skipped for missing kb_id=%s", normalized_kb_id)
                self._known_deleted_kb_ids.add(normalized_kb_id)
                self._known_kb_ids.discard(normalized_kb_id)
                return
            raise RuntimeError(
                f"auto-delete kb_id={normalized_kb_id} failed with HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"auto-delete kb_id={normalized_kb_id} failed: {exc}") from exc
        self._known_kb_ids.discard(normalized_kb_id)
        self._known_deleted_kb_ids.add(normalized_kb_id)
