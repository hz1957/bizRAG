from __future__ import annotations

import asyncio
import inspect
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv
from ultrarag.api import PipelineCall

PIPELINES_DIR = Path(__file__).resolve().parents[2] / "pipelines"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _prepare_runtime_env() -> None:
    dotenv_path = PROJECT_ROOT / ".env"
    if dotenv_path.is_file():
        load_dotenv(dotenv_path=dotenv_path, override=False)

    hf_cache_dir = str(os.environ.get("HF_CACHE_DIR") or "").strip()
    if not hf_cache_dir:
        return

    hf_home = Path(hf_cache_dir)
    if not hf_home.is_absolute():
        hf_home = (PROJECT_ROOT / hf_home).resolve()

    os.environ.setdefault("HF_HOME", str(hf_home))
    hub_cache = str(Path(os.environ["HF_HOME"]) / "hub")
    os.environ.setdefault("HF_HUB_CACHE", hub_cache)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", hub_cache)


async def _await_pipeline_call(
    *,
    pipeline_file: str,
    parameter_file: str,
    log_level: str,
) -> Any:
    result = PipelineCall(
        pipeline_file=pipeline_file,
        parameter_file=parameter_file,
        log_level=log_level,
    )
    if inspect.isawaitable(result):
        return await result
    return result


def _execute_pipeline_call(
    *,
    pipeline_file: str,
    parameter_file: str,
    log_level: str,
) -> Any:
    _prepare_runtime_env()
    return asyncio.run(
        _await_pipeline_call(
            pipeline_file=pipeline_file,
            parameter_file=parameter_file,
            log_level=log_level,
        )
    )


class UltraRAGPipelineRunner:
    def __init__(self, pipelines_dir: Optional[Path] = None) -> None:
        self._pipelines_dir = pipelines_dir or PIPELINES_DIR

    def _pipeline_paths(self, pipeline_name: str) -> tuple[Path, Path]:
        pipeline_file = self._pipelines_dir / f"{pipeline_name}.yaml"
        if not pipeline_file.is_file():
            raise FileNotFoundError(f"Pipeline config not found: {pipeline_file}")
        server_companion = pipeline_file.parent / "server" / (
            f"{pipeline_file.stem}_server.yaml"
        )
        if not server_companion.is_file():
            raise FileNotFoundError(
                f"Pipeline server companion not found: {server_companion}"
            )
        return pipeline_file, server_companion

    async def run(
        self,
        pipeline_name: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        log_level: str = "error",
    ) -> Any:
        pipeline_file, server_companion = self._pipeline_paths(pipeline_name)
        payload = params or {}

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            encoding="utf-8",
            delete=False,
        ) as handle:
            yaml.safe_dump(payload, handle, allow_unicode=True, sort_keys=False)
            temp_param_path = handle.name

        try:
            return await asyncio.to_thread(
                _execute_pipeline_call,
                pipeline_file=str(pipeline_file),
                parameter_file=temp_param_path,
                log_level=log_level,
            )
        finally:
            Path(temp_param_path).unlink(missing_ok=True)


DEFAULT_PIPELINE_RUNNER = UltraRAGPipelineRunner()
