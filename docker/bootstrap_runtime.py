from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Iterable

from huggingface_hub import snapshot_download

from bizrag.service.ultrarag.server_parameters import load_server_parameters

LOGGER = logging.getLogger("bizrag.bootstrap")
LOG_LEVEL = os.environ.get("BIZRAG_BOOTSTRAP_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

LEGACY_MINICPM_EMBEDDING_MODEL = "openbmb/MiniCPM-Embedding-Light"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-large-zh-v1.5"
DEFAULT_SOURCE_PARAMETERS_PATH = "/app/bizrag/servers/retriever/parameter.docker.yaml"
DEFAULT_FILE_SERVICE_WATCH_ROOT = "/app/runtime/file_service/watch"
DEFAULT_FILE_SERVICE_STORAGE_ROOT = "/app/runtime/file_service/storage"
DEFAULT_FILE_SERVICE_DATABASE = "/app/runtime/file_service/state/metadata.db"
DEFAULT_FILE_SERVICE_WATCH_DEFAULT_KB_ID = "contracts_compose_auto"
DEFAULT_MINERU_MODEL_TYPE = "pipeline"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _canonicalize_hf_model_ref(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("models--") and "/" not in normalized:
        cache_ref = normalized[len("models--") :]
        if "--" in cache_ref:
            org, repo = cache_ref.split("--", 1)
            if org and repo:
                normalized = f"{org}/{repo}"
    if normalized == LEGACY_MINICPM_EMBEDDING_MODEL:
        return DEFAULT_EMBEDDING_MODEL
    return normalized


def _resolve_path(value: str | Path) -> Path:
    return Path(str(value)).expanduser().resolve()


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    LOGGER.info("ensured directory path=%s", path)


def _ensure_path_parent(value: str) -> None:
    if "://" in value:
        return
    _ensure_directory(_resolve_path(value).parent)


def _iter_runtime_directories() -> Iterable[Path]:
    app_root = _resolve_path(os.environ.get("APP_ROOT", "/app"))
    workspace_root = _resolve_path(os.environ.get("BIZRAG_WORKSPACE_ROOT", str(app_root / "runtime" / "kbs")))
    watch_root = _resolve_path(os.environ.get("FILE_SERVICE_WATCH_ROOT", DEFAULT_FILE_SERVICE_WATCH_ROOT))
    storage_root = _resolve_path(os.environ.get("FILE_SERVICE_STORAGE_ROOT", DEFAULT_FILE_SERVICE_STORAGE_ROOT))
    hf_home = _resolve_path(os.environ.get("HF_HOME", str(app_root / ".cache" / "huggingface")))
    hf_hub_cache = _resolve_path(os.environ.get("HF_HUB_CACHE", str(hf_home / "hub")))
    modelscope_cache = _resolve_path(os.environ.get("MODELSCOPE_CACHE", str(hf_hub_cache / "modelscope")))
    default_kb_id = str(
        os.environ.get("FILE_SERVICE_WATCH_DEFAULT_KB_ID", DEFAULT_FILE_SERVICE_WATCH_DEFAULT_KB_ID)
    ).strip()

    dirs = [
        app_root / "runtime",
        workspace_root,
        watch_root,
        storage_root,
        _resolve_path(os.environ.get("FILE_SERVICE_DATABASE", DEFAULT_FILE_SERVICE_DATABASE)).parent,
        hf_home,
        hf_hub_cache,
        modelscope_cache,
        app_root / "logs",
        app_root / "output",
        app_root / "raw_knowledge",
    ]

    metadata_db = str(os.environ.get("BIZRAG_METADATA_DB", "") or "").strip()
    if metadata_db and "://" not in metadata_db:
        dirs.append(_resolve_path(metadata_db).parent)

    if default_kb_id:
        dirs.append(watch_root / default_kb_id)

    return dirs


def _load_bootstrap_model_config() -> dict:
    source_parameters_path = str(
        os.environ.get("BIZRAG_BOOTSTRAP_SOURCE_PARAMETERS_PATH", DEFAULT_SOURCE_PARAMETERS_PATH) or DEFAULT_SOURCE_PARAMETERS_PATH
    ).strip()
    if not source_parameters_path:
        raise RuntimeError("BIZRAG_BOOTSTRAP_SOURCE_PARAMETERS_PATH is empty")
    resolved_path = _resolve_path(source_parameters_path)
    LOGGER.info("loading bootstrap source parameters path=%s", resolved_path)
    return load_server_parameters(resolved_path)


def _existing_local_model_path(model_ref: str) -> Path | None:
    candidate = Path(model_ref).expanduser()
    if candidate.exists():
        return candidate.resolve()
    return None


def _ensure_hf_model_snapshot(model_ref: str, *, offline: bool) -> None:
    normalized = _canonicalize_hf_model_ref(model_ref)
    if not normalized:
        return

    local_path = _existing_local_model_path(normalized)
    if local_path is not None:
        LOGGER.info("skipping HF download for local model path=%s", local_path)
        return

    token = str(os.environ.get("HF_TOKEN", "") or "").strip() or None
    try:
        cached_path = snapshot_download(
            repo_id=normalized,
            local_files_only=True,
            token=token,
        )
        LOGGER.info("HF model cache hit repo=%s path=%s", normalized, cached_path)
        return
    except Exception as exc:
        if offline:
            raise RuntimeError(
                f"HF model cache missing for {normalized} while BIZRAG_HF_OFFLINE=true"
            ) from exc
        LOGGER.info("HF model cache miss repo=%s; downloading", normalized)

    downloaded_path = snapshot_download(
        repo_id=normalized,
        local_files_only=False,
        token=token,
    )
    LOGGER.info("HF model downloaded repo=%s path=%s", normalized, downloaded_path)


def _mineru_expected_relative_paths(model_type: str) -> list[tuple[str, list[str]]]:
    from mineru.utils.enum_class import ModelPath

    expected: list[tuple[str, list[str]]] = []
    if model_type in {"pipeline", "all"}:
        expected.append(
            (
                "pipeline",
                [
                    ModelPath.pp_doclayout_v2,
                    ModelPath.unimernet_small,
                    ModelPath.pytorch_paddle,
                    ModelPath.slanet_plus,
                    ModelPath.unet_structure,
                    ModelPath.paddle_table_cls,
                    ModelPath.paddle_orientation_classification,
                    ModelPath.pp_formulanet_plus_m,
                ],
            )
        )
    if model_type in {"vlm", "all"}:
        expected.append(("vlm", []))
    return expected


def _mineru_cache_ready(model_type: str) -> bool:
    try:
        from mineru.utils.config_reader import get_local_models_dir
    except ImportError:
        return False

    models_dir = get_local_models_dir() or {}
    if not isinstance(models_dir, dict):
        return False

    for repo_mode, expected_rel_paths in _mineru_expected_relative_paths(model_type):
        root = str(models_dir.get(repo_mode) or "").strip()
        if not root:
            return False
        root_path = _resolve_path(root)
        if not root_path.exists():
            return False
        for relative_path in expected_rel_paths:
            if not (root_path / relative_path).exists():
                return False
    return True


def _ensure_mineru_models(*, offline: bool) -> None:
    model_type = str(
        os.environ.get("BIZRAG_BOOTSTRAP_MINERU_MODEL_TYPE", DEFAULT_MINERU_MODEL_TYPE) or DEFAULT_MINERU_MODEL_TYPE
    ).strip().lower()
    if model_type not in {"pipeline", "vlm", "all"}:
        raise RuntimeError(
            "BIZRAG_BOOTSTRAP_MINERU_MODEL_TYPE must be one of: pipeline, vlm, all"
        )

    if _mineru_cache_ready(model_type):
        LOGGER.info("MinerU cache already ready model_type=%s", model_type)
        return

    if offline:
        raise RuntimeError(
            f"MinerU cache missing for model_type={model_type} while BIZRAG_HF_OFFLINE=true"
        )

    source = str(os.environ.get("MINERU_MODEL_SOURCE", "modelscope") or "modelscope").strip().lower()
    if source == "local":
        raise RuntimeError(
            f"MinerU cache missing for model_type={model_type} while MINERU_MODEL_SOURCE=local"
        )
    if source not in {"huggingface", "modelscope"}:
        raise RuntimeError("MINERU_MODEL_SOURCE must be one of: huggingface, modelscope, local")

    cmd = [
        "mineru-models-download",
        "--source",
        source,
        "--model_type",
        model_type,
    ]
    LOGGER.info("downloading MinerU models source=%s model_type=%s", source, model_type)
    subprocess.run(cmd, check=True)
    if not _mineru_cache_ready(model_type):
        raise RuntimeError(f"MinerU cache verification failed after download for model_type={model_type}")
    LOGGER.info("MinerU cache ready model_type=%s", model_type)


def _bootstrap_runtime_directories() -> None:
    for directory in _iter_runtime_directories():
        _ensure_directory(directory)

    file_service_database = str(
        os.environ.get("FILE_SERVICE_DATABASE", DEFAULT_FILE_SERVICE_DATABASE) or DEFAULT_FILE_SERVICE_DATABASE
    ).strip()
    _ensure_path_parent(file_service_database)


def _bootstrap_default_models() -> None:
    cfg = _load_bootstrap_model_config()
    offline = _env_bool("BIZRAG_HF_OFFLINE", False)

    retriever_cfg = cfg.get("retriever") or {}
    reranker_cfg = cfg.get("reranker") or {}

    retriever_backend = str(retriever_cfg.get("backend") or retriever_cfg.get("retriever_backend") or "").strip().lower()
    if retriever_backend in {"sentence_transformers", "infinity"}:
        model_ref = str(
            retriever_cfg.get("model_name_or_path")
            or retriever_cfg.get("retriever_model_name_or_path")
            or ""
        ).strip()
        _ensure_hf_model_snapshot(model_ref, offline=offline)

    reranker_backend = str(reranker_cfg.get("backend") or "").strip().lower()
    if reranker_backend in {"sentence_transformers", "infinity"}:
        model_ref = str(reranker_cfg.get("model_name_or_path") or "").strip()
        _ensure_hf_model_snapshot(model_ref, offline=offline)

    if _env_bool("BIZRAG_BOOTSTRAP_MINERU", True):
        _ensure_mineru_models(offline=offline)


def main() -> int:
    if _env_bool("BIZRAG_BOOTSTRAP_RUNTIME", True):
        _bootstrap_runtime_directories()

    if _env_bool("BIZRAG_BOOTSTRAP_MODELS", True):
        _bootstrap_default_models()

    mineru_json = Path.home() / os.environ.get("MINERU_TOOLS_CONFIG_JSON", "mineru.json")
    if mineru_json.is_file():
        try:
            payload = json.loads(mineru_json.read_text(encoding="utf-8"))
            LOGGER.info("MinerU config path=%s models-dir=%s", mineru_json, payload.get("models-dir"))
        except Exception:
            LOGGER.warning("failed to inspect MinerU config path=%s", mineru_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
