from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import ultrarag.client as ultrarag_client
from dotenv import load_dotenv
from ultrarag.mcp_logging import get_logger

from bizrag.common.io_utils import load_yaml

PIPELINES_DIR = Path(__file__).resolve().parents[2] / "pipelines"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
_REMOTE_NODE_READY = False
logger = logging.getLogger("bizrag.pipeline_runner")


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


def _ensure_remote_mcp_runtime() -> None:
    global _REMOTE_NODE_READY
    if _REMOTE_NODE_READY:
        return
    try:
        ultrarag_client.check_node_version(20)
        _REMOTE_NODE_READY = True
    except ultrarag_client.NodeNotInstalledError as exc:
        raise RuntimeError(
            "Remote MCP servers require Node.js >= 20, but Node.js was not found."
        ) from exc
    except ultrarag_client.NodeVersionTooLowError as exc:
        raise RuntimeError(
            "Remote MCP servers require Node.js >= 20, but the installed version is too low."
        ) from exc


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
            try:
                await self.client.__aexit__(None, None, None)
            except asyncio.CancelledError:
                logger.debug("Pipeline client shutdown was cancelled; ignoring during cleanup")
            self.entered = False


class UltraRAGPipelineRunner:
    def __init__(self, pipelines_dir: Optional[Path] = None) -> None:
        self._pipelines_dir = pipelines_dir or PIPELINES_DIR
        self._sessions: Dict[str, _PersistentPipelineSession] = {}
        self._sessions_lock = asyncio.Lock()

    def _pipeline_path(self, pipeline_name: str) -> Path:
        pipeline_file = self._pipelines_dir / f"{pipeline_name}.yaml"
        if not pipeline_file.is_file():
            raise FileNotFoundError(f"Pipeline config not found: {pipeline_file}")
        return pipeline_file

    def _load_pipeline_context(self, pipeline_file: Path) -> Dict[str, Any]:
        init_cfg = load_yaml(pipeline_file)
        server_paths = init_cfg.get("servers", {}) or {}
        pipeline_cfg = init_cfg.get("pipeline", []) or []

        server_cfg: Dict[str, Dict[str, Any]] = {}
        for name, relative_server_dir in server_paths.items():
            server_dir = Path(str(relative_server_dir))
            if not server_dir.is_absolute():
                server_dir = (PROJECT_ROOT / server_dir).resolve()
            server_cfg[name] = load_yaml(server_dir / "server.yaml")

        cfg_name = pipeline_file.stem
        param_config_path = pipeline_file.parent / "parameter" / f"{cfg_name}_parameter.yaml"
        param_cfg = load_yaml(param_config_path) if param_config_path.is_file() else {}
        for srv_name in server_cfg.keys():
            server_cfg[srv_name]["parameter"] = param_cfg.get(srv_name, {})

        mcp_cfg = {"mcpServers": {}}
        for name, sc in server_cfg.items():
            path = str(sc.get("path", "") or "")
            if path.endswith(".py"):
                mcp_cfg["mcpServers"][name] = {
                    "command": "python",
                    "args": [path],
                    "env": os.environ.copy(),
                }
            elif path.startswith(("http://", "https://")):
                _ensure_remote_mcp_runtime()
                mcp_cfg["mcpServers"][name] = {
                    "command": "npx",
                    "args": ["-y", "mcp-remote", path],
                    "env": os.environ.copy(),
                }
            else:
                raise ValueError(f"Unsupported server type for {name}: {path}")

        return {
            "config_path": str(pipeline_file),
            "param_config_path": param_config_path,
            "cfg_name": cfg_name,
            "mcp_cfg": mcp_cfg,
            "server_cfg": server_cfg,
            "pipeline_cfg": pipeline_cfg,
            "init_cfg": init_cfg,
        }

    async def _get_session(
        self,
        *,
        pipeline_name: str,
        log_level: str,
    ) -> _PersistentPipelineSession:
        async with self._sessions_lock:
            session = self._sessions.get(pipeline_name)
            if session is None:
                pipeline_file = self._pipeline_path(pipeline_name)
                _prepare_runtime_env()
                _configure_ultrarag_logging(log_level)
                context = self._load_pipeline_context(pipeline_file)
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
            try:
                await session.close()
            except asyncio.CancelledError:
                logger.debug("Pipeline session shutdown was cancelled; ignoring during cleanup")


DEFAULT_PIPELINE_RUNNER = UltraRAGPipelineRunner()
