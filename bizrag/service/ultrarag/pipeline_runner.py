from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import ultrarag.client as ultrarag_client
from dotenv import load_dotenv
from ultrarag.mcp_logging import get_logger

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

    hf_offline = str(os.environ.get("BIZRAG_HF_OFFLINE", "true") or "true").strip().lower()
    if hf_offline in {"1", "true", "yes", "on", "y"}:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def _configure_ultrarag_logging(log_level: str) -> None:
    normalized = str(log_level or "error").lower()
    os.environ["log_level"] = normalized
    ultrarag_client.logger = get_logger("Client", normalized)


@dataclass
class _PersistentPipelineSession:
    context: Dict[str, Any]
    client: Any
    entered: bool = False
    run_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    start_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def ensure_started(self) -> None:
        async with self.start_lock:
            if self.entered:
                return
            await self.client.__aenter__()
            self.entered = True

    async def close(self) -> None:
        async with self.start_lock:
            if not self.entered:
                return
            await self.client.__aexit__(None, None, None)
            self.entered = False


class UltraRAGPipelineRunner:
    def __init__(self, pipelines_dir: Optional[Path] = None) -> None:
        self._pipelines_dir = pipelines_dir or PIPELINES_DIR
        self._sessions: Dict[str, _PersistentPipelineSession] = {}
        self._sessions_lock = asyncio.Lock()

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

    async def _get_session(
        self,
        *,
        pipeline_name: str,
        log_level: str,
    ) -> _PersistentPipelineSession:
        async with self._sessions_lock:
            session = self._sessions.get(pipeline_name)
            if session is None:
                pipeline_file, _ = self._pipeline_paths(pipeline_name)
                _prepare_runtime_env()
                _configure_ultrarag_logging(log_level)
                context = ultrarag_client.load_pipeline_context(str(pipeline_file))
                session = _PersistentPipelineSession(
                    context=context,
                    client=ultrarag_client.create_mcp_client(context["mcp_cfg"]),
                )
                self._sessions[pipeline_name] = session
        await session.ensure_started()
        return session

    async def run(
        self,
        pipeline_name: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        log_level: str = "error",
    ) -> Any:
        _prepare_runtime_env()
        _configure_ultrarag_logging(log_level)
        session = await self._get_session(
            pipeline_name=pipeline_name,
            log_level=log_level,
        )
        async with session.run_lock:
            return await ultrarag_client.execute_pipeline(
                session.client,
                session.context,
                return_all=True,
                override_params=params or {},
            )

    async def warmup(
        self,
        pipeline_name: str,
        *,
        log_level: str = "error",
    ) -> None:
        _prepare_runtime_env()
        _configure_ultrarag_logging(log_level)
        await self._get_session(
            pipeline_name=pipeline_name,
            log_level=log_level,
        )

    async def close(self) -> None:
        async with self._sessions_lock:
            sessions = list(self._sessions.values())
            self._sessions = {}
        for session in sessions:
            await session.close()


DEFAULT_PIPELINE_RUNNER = UltraRAGPipelineRunner()
