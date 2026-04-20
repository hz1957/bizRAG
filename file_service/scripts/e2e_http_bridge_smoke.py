#!/usr/bin/env python
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


FILE_SERVICE_HOST = "127.0.0.1"
FILE_SERVICE_PORT = 8109
BROKER_PORT = 8210
TIMEOUT_SECONDS = 60


@dataclass
class CapturedPayload:
    path: str
    payload: dict[str, Any]


def _wait_for_health(url: str, timeout_seconds: int) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            r = requests.get(f"{url}/api/v1/files/health", timeout=1)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"health check timeout for {url}")


def _check_db_status(db_path: str) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(db_path)
    try:
        rows = list(
            conn.execute(
                """
                SELECT event_id, event_type, status
                FROM outbox_events
                ORDER BY created_at DESC
                """,
            ).fetchall()
        )
        return rows
    finally:
        conn.close()


class FakeBizRAGHTTPHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length > 0 else b""

        parsed = urlparse(self.path)
        if parsed.path != "/api/v1/events/rustfs/queue/batch":
            self.send_response(404)
            self.end_headers()
            return

        content = {}
        try:
            content = json.loads(raw_body.decode("utf-8"))
        except Exception:
            content = {}

        if not isinstance(content, dict):
            content = {}

        if not isinstance(content.get("events"), list):
            content["events"] = []

        app = self.server  # type: ignore[assignment]
        app.captured.append(CapturedPayload(path=self.path, payload=content))

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({"status": "ok", "received": len(content.get("events", []))}).encode("utf-8")
        )

    def log_message(self, *args: object, **kwargs: object) -> None:  # noqa: D401
        return


def _start_fake_bizrag_server() -> tuple[HTTPServer, threading.Thread]:
    class _Server(HTTPServer):
        captured: list[CapturedPayload]

    server = _Server((FILE_SERVICE_HOST, BROKER_PORT), FakeBizRAGHTTPHandler)
    server.captured = []

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main() -> None:
    workspace = Path("/tmp/file_service_e2e")
    db_path = workspace / "metadata.db"
    storage_root = workspace / "storage"
    workspace.mkdir(parents=True, exist_ok=True)

    server, _ = _start_fake_bizrag_server()

    env = os.environ.copy()
    env.update(
        {
            "FILE_SERVICE_HOST": FILE_SERVICE_HOST,
            "FILE_SERVICE_PORT": str(FILE_SERVICE_PORT),
            "FILE_SERVICE_STORAGE_ROOT": str(storage_root),
            "FILE_SERVICE_DATABASE": str(db_path),
            "FILE_SERVICE_BASE_URL": f"http://{FILE_SERVICE_HOST}:{FILE_SERVICE_PORT}",
            "FILE_SERVICE_PUBLISHER_BACKEND": "http",
            "FILE_SERVICE_HTTP_BRIDGE_URL": f"http://{FILE_SERVICE_HOST}:{BROKER_PORT}",
            "FILE_SERVICE_POLL_INTERVAL": "1",
        }
    )

    proc = subprocess.Popen(
        ["python", "-m", "file_service.run"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    base_url = f"http://{FILE_SERVICE_HOST}:{FILE_SERVICE_PORT}"
    try:
        _wait_for_health(base_url, TIMEOUT_SECONDS)

        create_resp = requests.post(
            f"{base_url}/api/v1/files/",
            data={
                "kb_id": "e2e_kb",
                "tenant_id": "tenant_e2e",
                "file_name": "smoke.txt",
            },
            files={"file": ("smoke.txt", b"hello from file service"),},
            timeout=5,
        )
        create_resp.raise_for_status()
        create_body = create_resp.json()
        file_id = create_body["file_id"]

        update_resp = requests.put(
            f"{base_url}/api/v1/files/{file_id}/content",
            data={"file_name": "smoke_v2.txt"},
            files={"file": ("smoke_v2.txt", b"updated payload"),},
            timeout=5,
        )
        update_resp.raise_for_status()

        delete_resp = requests.delete(f"{base_url}/api/v1/files/{file_id}", timeout=5)
        delete_resp.raise_for_status()

        # wait a bit to let async publisher flush events to fake endpoint
        time.sleep(2.0)

        db_rows = _check_db_status(str(db_path))
        if not db_rows:
            raise RuntimeError("no outbox rows were written")
        if any(status != "published" for _, _, status in db_rows):
            raise RuntimeError(f"there are unpublished events: {db_rows}")

        events = [item.payload for item in getattr(server, "captured", [])]
        event_types = sorted(
            {
                evt.get("event_type")
                for item in events
                for evt in item.get("events", [])
                if isinstance(evt, dict)
            },
        )
        if {"document.created", "document.updated", "document.deleted"}.issubset(event_types):
            print("e2e-ok")
            return

        if not events:
            raise RuntimeError("fake bizrag endpoint received no payload")
        raise RuntimeError(f"unexpected event types: {event_types}")
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        server.shutdown()


if __name__ == "__main__":
    main()
