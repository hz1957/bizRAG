from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List

from watchfiles import watch

APP_ROOT = Path(os.environ.get("APP_ROOT", "/app"))
PYTHON_BIN = sys.executable

WATCH_PATHS = [
    APP_ROOT / "bizrag",
    APP_ROOT / "docker",
    APP_ROOT / "pyproject.toml",
]
ALLOWED_SUFFIXES = {".py", ".yaml", ".yml", ".sh", ".toml", ".md"}
IGNORED_PARTS = {
    "__pycache__",
    ".git",
    ".venv",
    "runtime",
    "logs",
    "output",
    "build",
}


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _should_watch(_: object, path: str) -> bool:
    target = Path(path)
    if any(part in IGNORED_PARTS for part in target.parts):
        return False
    return target.suffix in ALLOWED_SUFFIXES or target.name == "pyproject.toml"


def _build_process_commands() -> Dict[str, List[str]]:
    commands: Dict[str, List[str]] = {}

    if _env_flag("BIZRAG_RUN_MQ_BRIDGE", True):
        backend = os.environ.get("BIZRAG_MQ_BACKEND", "rabbitmq").strip().lower()
        if backend != "none":
            metadata_db = os.environ.get("BIZRAG_METADATA_DB", str(APP_ROOT / "bizrag" / "state" / "metadata.db"))
            kb_registry = os.environ.get("BIZRAG_KB_REGISTRY", str(APP_ROOT / "bizrag" / "config" / "kb_registry.yaml"))
            workspace_root = os.environ.get("BIZRAG_WORKSPACE_ROOT", str(APP_ROOT / "runtime" / "kbs"))
            max_events = os.environ.get("BIZRAG_MAX_EVENTS_PER_MESSAGE", "100")
            if backend == "rabbitmq":
                commands["mq_bridge"] = [
                    PYTHON_BIN,
                    "-m",
                    "bizrag.service.rustfs_mq_bridge",
                    "--backend",
                    "rabbitmq",
                    "--metadata-db",
                    metadata_db,
                    "--kb-registry",
                    kb_registry,
                    "--workspace-root",
                    workspace_root,
                    "--amqp-url",
                    os.environ.get("BIZRAG_RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/"),
                    "--queue",
                    os.environ.get("BIZRAG_RABBITMQ_QUEUE", "bizrag.rustfs.events"),
                    "--prefetch-count",
                    os.environ.get("BIZRAG_RABBITMQ_PREFETCH", "20"),
                    "--max-events-per-message",
                    max_events,
                ]
            else:
                commands["mq_bridge"] = [
                    PYTHON_BIN,
                    "-m",
                    "bizrag.service.rustfs_mq_bridge",
                    "--backend",
                    "kafka",
                    "--metadata-db",
                    metadata_db,
                    "--kb-registry",
                    kb_registry,
                    "--workspace-root",
                    workspace_root,
                    "--bootstrap-servers",
                    os.environ.get("BIZRAG_KAFKA_BOOTSTRAP", "kafka:9092"),
                    "--topic",
                    os.environ.get("BIZRAG_KAFKA_TOPIC", "bizrag.rustfs.events"),
                    "--group-id",
                    os.environ.get("BIZRAG_KAFKA_GROUP_ID", "bizrag-rustfs-bridge"),
                    "--max-events-per-message",
                    max_events,
                ]

    if _env_flag("BIZRAG_RUN_WORKER", True):
        commands["worker"] = [
            PYTHON_BIN,
            "-m",
            "bizrag.service.rustfs_worker",
            "--metadata-db",
            os.environ.get("BIZRAG_METADATA_DB", str(APP_ROOT / "bizrag" / "state" / "metadata.db")),
            "--kb-registry",
            os.environ.get("BIZRAG_KB_REGISTRY", str(APP_ROOT / "bizrag" / "config" / "kb_registry.yaml")),
            "--workspace-root",
            os.environ.get("BIZRAG_WORKSPACE_ROOT", str(APP_ROOT / "runtime" / "kbs")),
            "--poll-interval",
            os.environ.get("BIZRAG_WORKER_POLL_INTERVAL", "2.0"),
            "--batch-size",
            os.environ.get("BIZRAG_WORKER_BATCH_SIZE", "10"),
        ]

    if _env_flag("BIZRAG_RUN_API", True):
        commands["api"] = [
            PYTHON_BIN,
            "-m",
            "bizrag.entrypoints.retrieve_api",
            "--retriever-config",
            os.environ.get("BIZRAG_RETRIEVER_CONFIG", str(APP_ROOT / "bizrag" / "config" / "retriever_docker.yaml")),
            "--kb-registry",
            os.environ.get("BIZRAG_KB_REGISTRY", str(APP_ROOT / "bizrag" / "config" / "kb_registry.yaml")),
            "--metadata-db",
            os.environ.get("BIZRAG_METADATA_DB", str(APP_ROOT / "bizrag" / "state" / "metadata.db")),
            "--workspace-root",
            os.environ.get("BIZRAG_WORKSPACE_ROOT", str(APP_ROOT / "runtime" / "kbs")),
            "--rustfs-token",
            os.environ.get("BIZRAG_RUSTFS_TOKEN", ""),
            "--rustfs-shared-secret",
            os.environ.get("BIZRAG_RUSTFS_SHARED_SECRET", ""),
            "--host",
            os.environ.get("BIZRAG_HOST", "0.0.0.0"),
            "--port",
            os.environ.get("BIZRAG_PORT", "64501"),
        ]

    return commands


def _start_processes() -> Dict[str, subprocess.Popen[bytes]]:
    commands = _build_process_commands()
    if not commands:
        raise RuntimeError("No BizRAG process is enabled for hot reload")

    procs: Dict[str, subprocess.Popen[bytes]] = {}
    for name, command in commands.items():
        print(f"[hot-reload] starting {name}: {' '.join(command)}", flush=True)
        procs[name] = subprocess.Popen(command, cwd=str(APP_ROOT))
    return procs


def _stop_processes(procs: Dict[str, subprocess.Popen[bytes]]) -> None:
    for proc in procs.values():
        if proc.poll() is None:
            proc.terminate()

    deadline = time.time() + 10
    while time.time() < deadline:
        if all(proc.poll() is not None for proc in procs.values()):
            return
        time.sleep(0.2)

    for proc in procs.values():
        if proc.poll() is None:
            proc.kill()
    for proc in procs.values():
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def _watch_changes(stop_event: threading.Event, restart_event: threading.Event) -> None:
    existing_paths = [str(path) for path in WATCH_PATHS if path.exists()]
    for changes in watch(
        *existing_paths,
        watch_filter=_should_watch,
        debounce=800,
        stop_event=stop_event,
        yield_on_timeout=False,
    ):
        if not changes:
            continue
        changed_paths = sorted({changed_path for _, changed_path in changes})
        preview = ", ".join(changed_paths[:5])
        if len(changed_paths) > 5:
            preview = f"{preview}, ..."
        print(f"[hot-reload] change detected: {preview}", flush=True)
        restart_event.set()
        return


def _collect_dead_processes(procs: Dict[str, subprocess.Popen[bytes]]) -> Iterable[str]:
    for name, proc in procs.items():
        if proc.poll() is not None:
            yield f"{name} exited with code {proc.returncode}"


def main() -> int:
    shutdown_event = threading.Event()

    def _handle_signal(signum: int, _: object) -> None:
        print(f"[hot-reload] received signal {signum}, shutting down", flush=True)
        shutdown_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    print("[hot-reload] enabled for bizrag container", flush=True)
    while not shutdown_event.is_set():
        procs = _start_processes()
        watch_stop_event = threading.Event()
        restart_event = threading.Event()
        watcher = threading.Thread(
            target=_watch_changes,
            args=(watch_stop_event, restart_event),
            daemon=True,
        )
        watcher.start()

        restart_reason = "source change"
        try:
            while not shutdown_event.is_set():
                if restart_event.is_set():
                    break
                dead = list(_collect_dead_processes(procs))
                if dead:
                    restart_reason = dead[0]
                    restart_event.set()
                    break
                time.sleep(0.5)
        finally:
            watch_stop_event.set()
            _stop_processes(procs)
            watcher.join(timeout=1)

        if shutdown_event.is_set():
            break

        print(f"[hot-reload] restarting because {restart_reason}", flush=True)
        time.sleep(0.5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
