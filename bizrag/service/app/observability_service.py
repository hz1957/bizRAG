from __future__ import annotations

import html
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional

from bizrag.common.time_utils import utc_now
from bizrag.infra.metadata_store import MetadataStore


MONITORED_COMPONENTS: List[Dict[str, Any]] = [
    {"id": "ingest", "label": "Ingest"},
    {"id": "queue", "label": "Queue"},
    {"id": "worker", "label": "Worker"},
    {"id": "index", "label": "Index"},
    {"id": "retrieve", "label": "Retrieve"},
    {"id": "extract", "label": "Extract"},
]


ALERT_RULES: List[Dict[str, Any]] = [
    {
        "id": "queue_backlog_high",
        "severity": "warning",
        "description": "Queued RustFS events exceed 20.",
    },
    {
        "id": "queue_backlog_critical",
        "severity": "critical",
        "description": "Queued RustFS events exceed 100.",
    },
    {
        "id": "worker_stalled",
        "severity": "critical",
        "description": "Queued events exist but no successful worker activity in the last 10 minutes.",
    },
    {
        "id": "retrieve_latency_high",
        "severity": "warning",
        "description": "Retrieve p95 latency exceeds 3000 ms in the recent window.",
    },
    {
        "id": "extract_latency_high",
        "severity": "warning",
        "description": "Extract p95 latency exceeds 4000 ms in the recent window.",
    },
    {
        "id": "failed_operations_recent",
        "severity": "warning",
        "description": "One or more operations failed in the recent window.",
    },
]


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _recent_items(rows: Iterable[Dict[str, Any]], *, minutes: int) -> List[Dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(1, minutes))
    items: List[Dict[str, Any]] = []
    for row in rows:
        started_at = _parse_ts(str(row.get("started_at") or row.get("created_at") or ""))
        if started_at is None or started_at >= cutoff:
            items.append(row)
    return items


def _percentile(values: List[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return float(ordered[idx])


def _latency_summary(rows: List[Dict[str, Any]]) -> Dict[str, float]:
    values = [
        float(row.get("duration_ms") or 0.0)
        for row in rows
        if row.get("duration_ms") is not None
    ]
    if not values:
        return {"count": 0.0, "p50_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0}
    return {
        "count": float(len(values)),
        "p50_ms": round(float(median(values)), 3),
        "p95_ms": round(_percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3),
    }


def _component_health_snapshot(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "status": "idle",
            "detail": "No recent activity",
            "status_counts": {},
            "latency_ms": _latency_summary([]),
            "last_started_at": None,
        }

    status_counts = Counter(str(row.get("status") or "unknown") for row in rows)
    latest = rows[0]
    latest_status = str(latest.get("status") or "unknown")
    successful_rows = [row for row in rows if str(row.get("status") or "") == "success"]
    snapshot_status = "up"
    if latest_status == "running":
        snapshot_status = "running"
    elif latest_status == "failed" and not successful_rows:
        snapshot_status = "degraded"
    elif latest_status == "failed":
        snapshot_status = "warning"

    last_started_at = str(latest.get("started_at") or "")
    detail = f'last={latest_status} total={len(rows)}'
    return {
        "status": snapshot_status,
        "detail": detail,
        "status_counts": dict(status_counts),
        "latency_ms": _latency_summary(rows),
        "last_started_at": last_started_at or None,
    }


class ObservabilityService:
    def __init__(self, *, store: MetadataStore) -> None:
        self._store = store

    def build_health_snapshot(self, *, read_service_status: str = "unknown") -> Dict[str, Any]:
        health_checks: List[Dict[str, Any]] = []
        try:
            self._store.count_kbs()
            metadata_ok = True
        except Exception as exc:
            metadata_ok = False
            health_checks.append(
                {
                    "name": "metadata_store",
                    "status": "down",
                    "detail": str(exc),
                }
            )
        else:
            health_checks.append(
                {
                    "name": "metadata_store",
                    "status": "up",
                    "detail": self._store.backend_name,
                }
            )

        health_checks.append(
            {
                "name": "read_service",
                "status": "up" if read_service_status == "ready" else "degraded",
                "detail": read_service_status,
            }
        )

        recent_rows = self._recent_operation_rows(window_minutes=30)
        queue_counts = self._store.count_rustfs_events_by_status()
        queued = int(queue_counts.get("queued") or 0)
        processing = int(queue_counts.get("processing") or 0) + int(
            queue_counts.get("running") or 0
        )
        queue_status = "up"
        if queued > 100:
            queue_status = "degraded"
        health_checks.append(
            {
                "name": "rustfs_queue",
                "status": queue_status,
                "detail": f"queued={queued} processing={processing}",
            }
        )

        by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in recent_rows:
            by_component[str(row.get("component") or "unknown")].append(row)

        for component in MONITORED_COMPONENTS:
            component_id = component["id"]
            snapshot = _component_health_snapshot(by_component.get(component_id, []))
            health_checks.append(
                {
                    "name": component_id,
                    "status": snapshot["status"],
                    "detail": snapshot["detail"],
                }
            )

        status = "ok"
        if not metadata_ok:
            status = "down"
        elif any(item["status"] in {"degraded", "warning"} for item in health_checks):
            status = "degraded"
        elif any(item["status"] == "running" for item in health_checks):
            status = "ok"
        return {
            "status": status,
            "generated_at": utc_now(),
            "checks": health_checks,
        }

    def _recent_operation_rows(self, *, limit: int = 400, window_minutes: int = 60) -> List[Dict[str, Any]]:
        rows = self._store.list_operation_spans(limit=limit)
        return _recent_items(rows, minutes=window_minutes)

    def _build_alerts(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        queue_counts = self._store.count_rustfs_events_by_status()
        queued = int(queue_counts.get("queued") or 0)
        if queued > 100:
            alerts.append({"rule_id": "queue_backlog_critical", "severity": "critical", "value": queued})
        elif queued > 20:
            alerts.append({"rule_id": "queue_backlog_high", "severity": "warning", "value": queued})

        failed_rows = [row for row in rows if str(row.get("status")) == "failed"]
        if failed_rows:
            alerts.append(
                {
                    "rule_id": "failed_operations_recent",
                    "severity": "warning",
                    "value": len(failed_rows),
                }
            )

        by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_component[str(row.get("component") or "unknown")].append(row)

        retrieve_ok = [
            row
            for row in by_component.get("retrieve", [])
            if str(row.get("status")) == "success"
        ]
        extract_ok = [
            row
            for row in by_component.get("extract", [])
            if str(row.get("status")) == "success"
        ]
        retrieve_p95 = _latency_summary(retrieve_ok)["p95_ms"]
        extract_p95 = _latency_summary(extract_ok)["p95_ms"]
        if retrieve_p95 > 3000:
            alerts.append(
                {
                    "rule_id": "retrieve_latency_high",
                    "severity": "warning",
                    "value": retrieve_p95,
                }
            )
        if extract_p95 > 4000:
            alerts.append(
                {
                    "rule_id": "extract_latency_high",
                    "severity": "warning",
                    "value": extract_p95,
                }
            )

        worker_successes = [
            row
            for row in by_component.get("worker", [])
            if str(row.get("status")) == "success"
        ]
        last_worker_success = None
        if worker_successes:
            last_worker_success = _parse_ts(str(worker_successes[0].get("started_at") or ""))
        if queued > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
            if last_worker_success is None or last_worker_success < cutoff:
                alerts.append(
                    {
                        "rule_id": "worker_stalled",
                        "severity": "critical",
                        "value": queued,
                    }
                )
        return alerts

    def build_overview(self, *, read_service_status: str = "unknown") -> Dict[str, Any]:
        recent_rows = self._recent_operation_rows()
        by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in recent_rows:
            by_component[str(row.get("component") or "unknown")].append(row)

        component_metrics = {}
        ordered_components = [
            component["id"] for component in MONITORED_COMPONENTS
        ] + sorted(component for component in by_component.keys() if component not in {c["id"] for c in MONITORED_COMPONENTS})
        seen = set()
        for component in ordered_components:
            if component in seen:
                continue
            seen.add(component)
            rows = by_component.get(component, [])
            snapshot = _component_health_snapshot(rows)
            component_metrics[component] = snapshot

        overview = {
            "generated_at": utc_now(),
            "health": self.build_health_snapshot(read_service_status=read_service_status),
            "inventory": {
                "kbs_total": self._store.count_kbs(),
                "documents_by_status": self._store.count_documents_by_status(),
                "tasks_by_status": self._store.count_tasks_by_status(),
                "rustfs_events_by_status": self._store.count_rustfs_events_by_status(),
            },
            "components": component_metrics,
            "alerts": self._build_alerts(recent_rows),
            "recent_spans": recent_rows[:100],
            "alert_rules": ALERT_RULES,
        }
        return overview

    def build_metrics_text(self, *, read_service_status: str = "unknown") -> str:
        overview = self.build_overview(read_service_status=read_service_status)
        lines: List[str] = []
        inventory = overview["inventory"]
        lines.append(f'bizrag_kbs_total {inventory["kbs_total"]}')
        for status, value in sorted(inventory["documents_by_status"].items()):
            lines.append(f'bizrag_documents_status{{status="{status}"}} {value}')
        for status, value in sorted(inventory["tasks_by_status"].items()):
            lines.append(f'bizrag_tasks_status{{status="{status}"}} {value}')
        for status, value in sorted(inventory["rustfs_events_by_status"].items()):
            lines.append(f'bizrag_rustfs_events_status{{status="{status}"}} {value}')
        for component, data in sorted(overview["components"].items()):
            latency = data["latency_ms"]
            for status, value in sorted(data["status_counts"].items()):
                lines.append(
                    f'bizrag_operation_status{{component="{component}",status="{status}"}} {value}'
                )
            lines.append(
                f'bizrag_operation_latency_p50_ms{{component="{component}"}} {latency["p50_ms"]}'
            )
            lines.append(
                f'bizrag_operation_latency_p95_ms{{component="{component}"}} {latency["p95_ms"]}'
            )
            lines.append(
                f'bizrag_operation_latency_max_ms{{component="{component}"}} {latency["max_ms"]}'
            )
        lines.append(
            f'bizrag_health_status{{status="{overview["health"]["status"]}"}} 1'
        )
        for check in overview["health"]["checks"]:
            lines.append(
                f'bizrag_component_health{{component="{check["name"]}",status="{check["status"]}"}} 1'
            )
        lines.append(f'bizrag_alerts_total {len(overview["alerts"])}')
        return "\n".join(lines) + "\n"

    def render_dashboard_html(self, *, read_service_status: str = "unknown") -> str:
        overview = self.build_overview(read_service_status=read_service_status)
        initial_json = json.dumps(overview, ensure_ascii=False).replace("</", "<\\/")
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>bizRAG Ops Dashboard</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{
      --bg: #f4f1ea;
      --card: #fffdf8;
      --ink: #1e1b16;
      --muted: #6e655a;
      --line: #d8d1c7;
      --good: #1f7a45;
      --warn: #a66300;
      --bad: #9f2f28;
      --accent: #0f4c5c;
      --idle: #7b7063;
      --running: #1d6fa5;
    }}
    body {{ margin: 0; font-family: Georgia, 'Iowan Old Style', serif; background: linear-gradient(180deg, #ede7db 0%, var(--bg) 100%); color: var(--ink); }}
    .wrap {{ max-width: 1320px; margin: 0 auto; padding: 28px; }}
    .hero {{ display:flex; justify-content:space-between; align-items:end; gap: 24px; margin-bottom: 24px; }}
    h1 {{ margin:0; font-size: 34px; }}
    .sub {{ color: var(--muted); font-size: 14px; }}
    .grid {{ display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 16px; margin-bottom: 20px; }}
    .grid-6 {{ display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 16px; margin-bottom: 20px; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px; box-shadow: 0 8px 24px rgba(30,27,22,0.06); }}
    .k {{ color: var(--muted); font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; }}
    .v {{ font-size: 28px; margin-top: 8px; }}
    .status-ok {{ color: var(--good); }}
    .status-degraded {{ color: var(--warn); }}
    .status-down {{ color: var(--bad); }}
    .status-warning {{ color: var(--warn); }}
    .status-idle {{ color: var(--idle); }}
    .status-running {{ color: var(--running); }}
    .section {{ margin-top: 18px; }}
    .section h2 {{ margin: 0 0 12px; font-size: 20px; }}
    table {{ width:100%; border-collapse: collapse; }}
    th, td {{ text-align:left; padding:10px 8px; border-bottom:1px solid var(--line); font-size:14px; vertical-align: top; }}
    th {{ color: var(--muted); font-weight:600; }}
    .alerts {{ display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px; }}
    .alert {{ border-radius: 14px; padding: 14px; border: 1px solid var(--line); background: #fff; display:flex; justify-content:space-between; gap:8px; }}
    .alert.warning {{ border-color: #d3a55d; background: #fff7ea; }}
    .alert.critical {{ border-color: #d66a62; background: #fff1ef; }}
    .empty {{ color: var(--muted); padding: 12px 0; }}
    .pill {{ display:inline-block; padding:4px 10px; border-radius:999px; background:#efe9df; color:var(--muted); font-size:12px; }}
    .health-grid {{ display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 12px; }}
    .health-item {{ border: 1px solid var(--line); border-radius: 14px; padding: 14px; background: #fff; }}
    .health-item .name {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }}
    .health-item .status {{ font-size: 20px; margin: 8px 0 4px; }}
    .health-item .detail {{ color: var(--muted); font-size: 13px; }}
    .toolbar {{ display:flex; gap: 12px; flex-wrap: wrap; margin-top: 16px; }}
    .toolbar button {{ border: 1px solid var(--line); background: var(--card); color: var(--ink); padding: 10px 14px; border-radius: 999px; cursor: pointer; font: inherit; }}
    .toolbar button:hover {{ border-color: var(--accent); color: var(--accent); }}
    .raw-panel {{ background: #16130f; color: #efe6da; border-radius: 14px; padding: 14px; overflow: auto; min-height: 240px; }}
    .raw-panel pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font: 12px/1.45 'SFMono-Regular', Menlo, monospace; }}
    dialog.raw-modal {{ width: min(1100px, 92vw); border: none; border-radius: 18px; padding: 0; box-shadow: 0 20px 60px rgba(0,0,0,0.28); }}
    dialog.raw-modal::backdrop {{ background: rgba(22, 19, 15, 0.5); }}
    .modal-shell {{ background: var(--card); color: var(--ink); }}
    .modal-head {{ display:flex; justify-content:space-between; align-items:center; padding: 16px 18px; border-bottom: 1px solid var(--line); }}
    .modal-head h3 {{ margin: 0; font-size: 18px; }}
    .modal-head button {{ border: 1px solid var(--line); background: #fff; border-radius: 999px; width: 34px; height: 34px; cursor: pointer; }}
    .modal-body {{ padding: 18px; }}
    .toolbar.compact {{ margin-top: 0; }}
    .input-row {{ display:flex; gap: 12px; align-items:center; flex-wrap: wrap; margin-top: 14px; }}
    .input-row input, .input-row select, .input-row textarea {{ min-width: 220px; flex: 1 1 220px; border: 1px solid var(--line); background: #fff; border-radius: 14px; padding: 10px 14px; font: inherit; }}
    .input-row textarea {{ min-height: 88px; resize: vertical; border-radius: 16px; }}
    .action-row {{ display:flex; gap: 12px; flex-wrap: wrap; margin-top: 14px; }}
    .action-row button {{ border: 1px solid var(--line); background: var(--card); color: var(--ink); padding: 10px 14px; border-radius: 999px; cursor: pointer; font: inherit; }}
    .action-row button.primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
    .action-row button:disabled {{ opacity: 0.6; cursor: wait; }}
    .query-result {{ margin-top: 14px; border: 1px solid var(--line); border-radius: 14px; background: #fff; padding: 14px; }}
    .query-result pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; font: 12px/1.5 'SFMono-Regular', Menlo, monospace; }}
    .query-meta {{ color: var(--muted); font-size: 13px; margin-top: 8px; }}
    .query-empty {{ color: var(--muted); font-size: 13px; }}
    .query-stack {{ display: grid; gap: 12px; margin-top: 12px; }}
    .query-answer {{ border: 1px solid var(--line); border-radius: 12px; background: #fcfaf6; padding: 14px; white-space: pre-wrap; word-break: break-word; }}
    .query-hit {{ border: 1px solid var(--line); border-radius: 12px; background: #fcfaf6; padding: 12px; }}
    .query-hit-head {{ display:flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
    .query-hit-title {{ font-weight: 700; }}
    .query-hit-score {{ color: var(--muted); font-size: 12px; white-space: nowrap; }}
    .query-hit-meta {{ display:flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .query-hit-meta span {{ padding: 2px 8px; border-radius: 999px; background: #f4efe8; }}
    .query-hit-content {{ margin-top: 10px; white-space: pre-wrap; word-break: break-word; line-height: 1.55; }}
    .query-raw {{ margin-top: 10px; }}
    .query-raw summary {{ cursor: pointer; color: var(--muted); font-size: 12px; }}
    .query-raw pre {{ margin-top: 8px; }}
    .scroll-panel {{ overflow-y: auto; overflow-x: auto; }}
    .spans-panel {{ max-height: 420px; }}
    .files-panel {{ max-height: 560px; }}
    .file-table-wrap {{ overflow:auto; margin-top: 14px; border: 1px solid var(--line); border-radius: 14px; background: #fff; }}
    .file-table td small {{ display:block; color: var(--muted); margin-top: 4px; }}
    .file-open {{ border: 1px solid var(--line); background: #fff; border-radius: 999px; padding: 6px 12px; cursor: pointer; }}
    .file-open:hover {{ border-color: var(--accent); color: var(--accent); }}
    .meta-list {{ margin: 10px 0 0; display:grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 8px 14px; }}
    .meta-list div {{ font-size: 13px; color: var(--muted); }}
    .meta-list strong {{ display:block; color: var(--ink); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 2px; }}
    .chunk-list {{ margin-top: 12px; border-top: 1px solid var(--line); padding-top: 12px; }}
    .chunk-item {{ position: relative; border: 1px solid var(--line); border-radius: 12px; padding: 10px; background: #fcfaf6; margin-top: 8px; }}
    .chunk-head {{ display:flex; justify-content:space-between; gap: 12px; font-size: 12px; color: var(--muted); }}
    .chunk-hover-note {{ margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .chunk-tooltip {{
      position: absolute;
      left: 12px;
      right: 12px;
      top: calc(100% + 8px);
      z-index: 10;
      display: none;
      border-radius: 12px;
      border: 1px solid #2d2923;
      background: #1d1a16;
      color: #f6efe5;
      box-shadow: 0 14px 30px rgba(30, 27, 22, 0.24);
      padding: 12px;
      font: 12px/1.5 'SFMono-Regular', Menlo, monospace;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .chunk-item:hover .chunk-tooltip,
    .chunk-item:focus-within .chunk-tooltip {{ display: block; }}
    @media (max-width: 1080px) {{
      .grid, .grid-6, .alerts, .health-grid, .meta-list {{ grid-template-columns: repeat(2, minmax(0,1fr)); }}
    }}
    @media (max-width: 640px) {{
      .grid, .grid-6, .alerts, .health-grid, .meta-list {{ grid-template-columns: 1fr; }}
      .hero {{ display:block; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1>bizRAG Ops Dashboard</h1>
        <div class="sub" id="generated-at">Generated at {html.escape(overview["generated_at"])} · auto-refresh every 15s</div>
      </div>
      <div class="pill" id="health-pill">health</div>
    </div>
    <div class="grid" id="inventory-grid">
    </div>
    <div class="card section">
      <h2>Alerts</h2>
      <div class="alerts" id="alerts"></div>
    </div>
    <div class="card section">
      <h2>Component Health</h2>
      <div class="health-grid" id="health-grid"></div>
    </div>
    <div class="card section">
      <h2>Component Metrics</h2>
      <table>
        <thead><tr><th>Component</th><th>Status Counts</th><th>P50 ms</th><th>P95 ms</th><th>Max ms</th></tr></thead>
        <tbody id="component-metrics"></tbody>
      </table>
    </div>
    <div class="card section">
      <h2>Recent Spans</h2>
      <div class="scroll-panel spans-panel">
        <table>
          <thead><tr><th>Started</th><th>Component</th><th>Operation</th><th>Status</th><th>Duration</th><th>KB</th></tr></thead>
          <tbody id="recent-spans"></tbody>
        </table>
      </div>
    </div>
    <div class="card section">
      <h2>Query Console</h2>
      <div class="sub">Send live retrieve or RAG requests against the running container service.</div>
      <div class="input-row">
        <select id="query-kb-id"></select>
        <input id="query-top-k" type="number" min="1" step="1" value="3" placeholder="Top K" />
      </div>
      <div class="input-row">
        <textarea id="query-text" placeholder="Enter a retrieval or RAG question"></textarea>
      </div>
      <div class="input-row">
        <textarea id="query-system-prompt" placeholder="Optional system prompt for RAG"></textarea>
      </div>
      <div class="action-row">
        <button type="button" onclick="runQuery('retrieve')">Retrieve</button>
        <button type="button" class="primary" onclick="runQuery('rag')">RAG</button>
      </div>
      <div class="query-result">
        <div class="sub" id="query-result-title">No request sent yet.</div>
        <div class="query-meta" id="query-result-meta"></div>
        <div id="query-result-body" class="query-empty">Use Retrieve to inspect matched chunks, or RAG to inspect the generated answer and citations.</div>
      </div>
    </div>
    <div class="card section">
      <h2>Data Tools</h2>
      <div class="sub">Open raw health, overview, metrics, and file inventory in a modal when needed.</div>
      <div class="toolbar compact">
        <button type="button" onclick="openRawModal('health')">Raw Health</button>
        <button type="button" onclick="openRawModal('overview')">Raw Overview</button>
        <button type="button" onclick="openRawModal('metrics')">Raw Metrics</button>
        <button type="button" onclick="openRawModal('files')">Raw File Inventory</button>
      </div>
    </div>
    <div class="card section">
      <h2>File Service Inventory</h2>
      <div class="sub">File service files mapped to UltraRAG chunk ids and Milvus vector ids.</div>
      <div id="file-service-summary" class="sub" style="margin-top:8px;"></div>
      <div class="input-row">
        <input id="file-search" type="search" placeholder="Search file name, kb_id, source_uri, file_id" oninput="renderFiles(currentFileInventory)" />
      </div>
      <div id="file-service-list" class="file-table-wrap scroll-panel files-panel"></div>
    </div>
  </div>
  <dialog id="raw-modal" class="raw-modal">
    <div class="modal-shell">
      <div class="modal-head">
        <h3 id="raw-modal-title">Raw Data</h3>
        <button type="button" onclick="closeRawModal()">×</button>
      </div>
      <div class="modal-body">
        <div class="raw-panel"><pre id="raw-modal-content"></pre></div>
      </div>
    </div>
  </dialog>
  <dialog id="file-modal" class="raw-modal">
    <div class="modal-shell">
      <div class="modal-head">
        <h3 id="file-modal-title">File Details</h3>
        <button type="button" onclick="closeFileModal()">×</button>
      </div>
      <div class="modal-body">
        <div class="meta-list" id="file-modal-meta"></div>
        <div class="chunk-list">
          <div class="sub">Chunks and Milvus vector ids</div>
          <div id="file-modal-chunks"></div>
        </div>
      </div>
    </div>
  </dialog>
  <script>
    const initialData = {initial_json};
    let currentFileInventory = {{ items: [] }};
    let currentKbItems = [];
    const rawPayloads = {{
      health: "",
      overview: "",
      metrics: "",
      files: "",
    }};
    function esc(value) {{
      return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    }}
    function badgeClass(status) {{
      return `status-${{status || "idle"}}`;
    }}
    function compact(value, limit = 72) {{
      const text = String(value ?? "");
      return text.length <= limit ? text : text.slice(0, limit - 1) + "…";
    }}
    function formatDuration(value) {{
      const ms = Number(value || 0);
      if (!Number.isFinite(ms) || ms <= 0) {{
        return "0 ms";
      }}
      if (ms >= 1000) {{
        return `${{(ms / 1000).toFixed(2)}} s`;
      }}
      return `${{ms.toFixed(1)}} ms`;
    }}
    function renderOverview(data) {{
      document.getElementById("generated-at").textContent = `Generated at ${{data.generated_at}} · auto-refresh every 15s`;
      const healthStatus = data.health?.status || "unknown";
      const pill = document.getElementById("health-pill");
      pill.textContent = `health: ${{healthStatus}}`;
      pill.className = `pill ${{badgeClass(healthStatus)}}`;

      const inventory = data.inventory || {{}};
      const inventoryCards = [
        ["Knowledge Bases", inventory.kbs_total || 0],
        ["Documents", Object.values(inventory.documents_by_status || {{}}).reduce((a, b) => a + b, 0)],
        ["Tasks", Object.values(inventory.tasks_by_status || {{}}).reduce((a, b) => a + b, 0)],
        ["Queued Events", (inventory.rustfs_events_by_status || {{}}).queued || 0],
      ];
      document.getElementById("inventory-grid").innerHTML = inventoryCards.map(([label, value]) => (
        `<div class="card"><div class="k">${{esc(label)}}</div><div class="v">${{esc(value)}}</div></div>`
      )).join("");

      const alerts = data.alerts || [];
      document.getElementById("alerts").innerHTML = alerts.length ? alerts.map((item) => (
        `<div class="alert ${{esc(item.severity)}}"><strong>${{esc(item.rule_id)}}</strong><span>${{esc(item.value)}}</span></div>`
      )).join("") : '<div class="empty">No active alerts</div>';

      const checks = data.health?.checks || [];
      document.getElementById("health-grid").innerHTML = checks.map((check) => (
        `<div class="health-item"><div class="name">${{esc(check.name)}}</div><div class="status ${{badgeClass(check.status)}}">${{esc(check.status)}}</div><div class="detail">${{esc(check.detail)}}</div></div>`
      )).join("");

      const components = data.components || {{}};
      document.getElementById("component-metrics").innerHTML = Object.entries(components).map(([name, item]) => (
        `<tr><td>${{esc(name)}}<div class="sub">${{esc(item.detail || "")}}</div></td><td>${{esc(JSON.stringify(item.status_counts || {{}}))}}</td><td>${{formatDuration(item.latency_ms?.p50_ms || 0)}}</td><td>${{formatDuration(item.latency_ms?.p95_ms || 0)}}</td><td>${{formatDuration(item.latency_ms?.max_ms || 0)}}</td></tr>`
      )).join("");

      const spans = data.recent_spans || [];
      document.getElementById("recent-spans").innerHTML = spans.slice(0, 30).map((item) => (
        `<tr><td>${{esc(item.started_at)}}</td><td>${{esc(item.component)}}</td><td>${{esc(item.operation)}}</td><td class="${{badgeClass(item.status)}}">${{esc(item.status)}}</td><td title="${{Number(item.duration_ms || 0).toFixed(1)}} ms">${{formatDuration(item.duration_ms || 0)}}</td><td>${{esc(item.kb_id || "")}}</td></tr>`
      )).join("");

      rawPayloads.health = JSON.stringify(data.health || {{}}, null, 2);
      rawPayloads.overview = JSON.stringify(data, null, 2);
    }}
    function renderFiles(data) {{
      currentFileInventory = data || {{ items: [] }};
      const items = data.items || [];
      const term = (document.getElementById("file-search")?.value || "").trim().toLowerCase();
      const filtered = term ? items.filter((item) => (
        [item.file_name, item.kb_id, item.source_uri, item.file_id].some((value) => String(value || "").toLowerCase().includes(term))
      )) : items;
      document.getElementById("file-service-summary").textContent =
        `generated at ${{data.generated_at || ""}} · files: ${{filtered.length}} / ${{items.length}} · db: ${{data.database_path || ""}}`;
      rawPayloads.files = JSON.stringify(data, null, 2);
      document.getElementById("file-service-list").innerHTML = filtered.length ? `
        <table class="file-table">
          <thead><tr><th>File</th><th>KB</th><th>Status</th><th>Chunks</th><th>Updated</th><th></th></tr></thead>
          <tbody>
            ${{filtered.map((item, idx) => `
              <tr>
                <td>${{esc(item.file_name || item.file_id)}}<small>${{esc(compact(item.source_uri, 88))}}</small></td>
                <td>${{esc(item.kb_id)}}</td>
                <td>${{esc(item.status)}}</td>
                <td>${{esc(item.chunk_count)}}</td>
                <td>${{esc(item.updated_at || "")}}</td>
                <td><button type="button" class="file-open" onclick="openFileModal(${{idx}})">Open</button></td>
              </tr>
            `).join("")}}
          </tbody>
        </table>
      ` : '<div class="empty">No file_service records found.</div>';
      currentFileInventory.filteredItems = filtered;
    }}
    function renderKbOptions(items) {{
      currentKbItems = Array.isArray(items) ? items : [];
      const select = document.getElementById("query-kb-id");
      if (!select) return;
      const options = currentKbItems.map((item) => {{
        const kbId = String(item.kb_id || "");
        return `<option value="${{esc(kbId)}}">${{esc(kbId)}}</option>`;
      }});
      select.innerHTML = options.length ? options.join("") : '<option value="">No KBs</option>';
      const preferred = currentKbItems.find((item) => String(item.kb_id || "").includes("contracts_compose_auto"));
      if (preferred) {{
        select.value = String(preferred.kb_id);
      }}
    }}
    async function refreshKbOptions() {{
      try {{
        const resp = await fetch("/api/v1/admin/kbs", {{ cache: "no-store" }});
        if (!resp.ok) {{
          throw new Error(`HTTP ${{resp.status}}`);
        }}
        const data = await resp.json();
        renderKbOptions(data.items || []);
      }} catch (err) {{
        console.error("failed to refresh kb list", err);
      }}
    }}
    function renderRawDetails(label, payload) {{
      return `
        <details class="query-raw">
          <summary>${{esc(label)}}</summary>
          <pre>${{esc(JSON.stringify(payload, null, 2))}}</pre>
        </details>
      `;
    }}
    function renderRetrieveResult(data) {{
      const items = Array.isArray(data?.items) ? data.items : [];
      if (!items.length) {{
        return '<div class="query-empty">No retrieval hits returned.</div>' + renderRawDetails("Raw response", data);
      }}
      return `
        <div class="query-stack">
          ${{items.map((item, index) => {{
            const sources = Array.isArray(item?.metadata?.retrieval_sources) ? item.metadata.retrieval_sources.join(", ") : "";
            return `
              <div class="query-hit">
                <div class="query-hit-head">
                  <div class="query-hit-title">${{esc(item.title || item.file_name || `Hit ${{index + 1}}`)}}</div>
                  <div class="query-hit-score">score ${{Number(item.score || 0).toFixed(4)}}</div>
                </div>
                <div class="query-hit-meta">
                  <span>file: ${{esc(item.file_name || "")}}</span>
                  <span>sheet: ${{esc(item.sheet_name || "")}}</span>
                  <span>row: ${{esc(item.row_index ?? "")}}</span>
                  <span>doc_id: ${{esc(item.doc_id || "")}}</span>
                  <span>source: ${{esc(sources || "unknown")}}</span>
                </div>
                <div class="query-hit-content">${{esc(item.content || "")}}</div>
                ${{renderRawDetails("Raw item", item)}}
              </div>
            `;
          }}).join("")}}
        </div>
        ${{renderRawDetails("Raw response", data)}}
      `;
    }}
    function renderRagResult(data) {{
      const citations = Array.isArray(data?.citations) ? data.citations : [];
      return `
        <div class="query-stack">
          <div class="query-answer">${{esc(data?.answer || "No answer returned.")}}</div>
          ${{citations.length ? citations.map((item, index) => `
            <div class="query-hit">
              <div class="query-hit-head">
                <div class="query-hit-title">${{esc(item.title || item.file_name || `Citation ${{index + 1}}`)}}</div>
                <div class="query-hit-score">score ${{Number(item.score || 0).toFixed(4)}}</div>
              </div>
              <div class="query-hit-meta">
                <span>file: ${{esc(item.file_name || "")}}</span>
                <span>sheet: ${{esc(item.sheet_name || "")}}</span>
                <span>row: ${{esc(item.row_index ?? "")}}</span>
                <span>doc_id: ${{esc(item.doc_id || "")}}</span>
              </div>
              <div class="query-hit-content">${{esc(item.content || "")}}</div>
              ${{renderRawDetails("Raw citation", item)}}
            </div>
          `).join("") : '<div class="query-empty">No citations returned.</div>'}}
        </div>
        ${{renderRawDetails("Raw response", data)}}
      `;
    }}
    function setQueryResult(title, body, meta = "") {{
      document.getElementById("query-result-title").textContent = title;
      document.getElementById("query-result-meta").textContent = meta;
      document.getElementById("query-result-body").innerHTML = body;
    }}
    async function runQuery(mode) {{
      const kbId = (document.getElementById("query-kb-id")?.value || "").trim();
      const query = (document.getElementById("query-text")?.value || "").trim();
      const topK = Number(document.getElementById("query-top-k")?.value || 3);
      const systemPrompt = (document.getElementById("query-system-prompt")?.value || "").trim();
      if (!kbId) {{
        setQueryResult("Missing KB", "Select a KB before sending a request.");
        return;
      }}
      if (!query) {{
        setQueryResult("Missing Query", "Enter a query before sending a request.");
        return;
      }}
      const buttons = Array.from(document.querySelectorAll(".action-row button"));
      for (const button of buttons) button.disabled = true;
      setQueryResult(`Running ${{mode}}...`, "");
      try {{
        const payload = {{
          kb_id: kbId,
          query,
          top_k: Number.isFinite(topK) && topK > 0 ? topK : 3,
        }};
        if (mode === "rag" && systemPrompt) {{
          payload.system_prompt = systemPrompt;
        }}
        const path = mode === "rag" ? "/api/v1/rag" : "/api/v1/retrieve";
        const startedAt = performance.now();
        const resp = await fetch(path, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(payload),
        }});
        const elapsedMs = performance.now() - startedAt;
        const text = await resp.text();
        let body = `<pre>${{esc(text)}}</pre>`;
        try {{
          const data = JSON.parse(text);
          body = mode === "rag" ? renderRagResult(data) : renderRetrieveResult(data);
        }} catch (_err) {{
        }}
        const meta = `kb_id=${{kbId}} · status=${{resp.status}} · elapsed=${{elapsedMs.toFixed(1)}} ms`;
        setQueryResult(`${{mode.toUpperCase()}} response`, body, meta);
      }} catch (err) {{
        setQueryResult(`${{mode.toUpperCase()}} failed`, String(err));
      }} finally {{
        for (const button of buttons) button.disabled = false;
      }}
    }}
    function openFileModal(index) {{
      const item = (currentFileInventory.filteredItems || [])[index];
      if (!item) return;
      document.getElementById("file-modal-title").textContent = item.file_name || item.file_id;
      document.getElementById("file-modal-meta").innerHTML = `
        <div><strong>File ID</strong>${{esc(item.file_id)}}</div>
        <div><strong>KB</strong>${{esc(item.kb_id)}}</div>
        <div><strong>Source URI</strong>${{esc(item.source_uri)}}</div>
        <div><strong>Status</strong>${{esc(item.status)}}</div>
        <div><strong>Version</strong>${{esc(item.current_version)}}</div>
        <div><strong>Storage Key</strong>${{esc(item.storage_key || "")}}</div>
        <div><strong>Storage Path</strong>${{esc(item.storage_path || "")}}</div>
        <div><strong>Chunk File</strong>${{esc(item.chunk_file || "")}}</div>
      `;
      const chunks = item.chunks || [];
      document.getElementById("file-modal-chunks").innerHTML = chunks.length ? chunks.map((chunk) => `
        <div class="chunk-item">
          <div class="chunk-head"><span>chunk_id: ${{esc(chunk.chunk_id)}}</span><span>vector_id: ${{esc(chunk.vector_id)}}</span></div>
          <div class="chunk-head"><span>doc_id: ${{esc(chunk.doc_id)}}</span><span>row: ${{esc(chunk.row_index ?? "")}}</span></div>
          <div class="chunk-hover-note">Hover to preview chunk text</div>
          <div class="chunk-tooltip">${{esc(chunk.snippet)}}</div>
        </div>
      `).join("") : '<div class="empty">No chunks found for this file in the current KB workspace.</div>';
      document.getElementById("file-modal").showModal();
    }}
    function closeFileModal() {{
      document.getElementById("file-modal").close();
    }}
    async function refreshOverview() {{
      try {{
        const resp = await fetch("/api/v1/admin/ops/overview", {{ cache: "no-store" }});
        if (!resp.ok) {{
            throw new Error(`HTTP ${{resp.status}}`);
        }}
        const data = await resp.json();
        renderOverview(data);
      }} catch (err) {{
        console.error("failed to refresh ops overview", err);
      }}
    }}
    async function refreshMetrics() {{
      try {{
        const resp = await fetch("/api/v1/admin/ops/metrics", {{ cache: "no-store" }});
        if (!resp.ok) {{
          throw new Error(`HTTP ${{resp.status}}`);
        }}
        const text = await resp.text();
        rawPayloads.metrics = text;
      }} catch (err) {{
        console.error("failed to refresh ops metrics", err);
      }}
    }}
    async function refreshFiles() {{
      try {{
        const resp = await fetch("/api/v1/admin/ops/files?limit=24&chunk_preview=8", {{ cache: "no-store" }});
        if (!resp.ok) {{
          throw new Error(`HTTP ${{resp.status}}`);
        }}
        const data = await resp.json();
        renderFiles(data);
      }} catch (err) {{
        console.error("failed to refresh file inventory", err);
      }}
    }}
    function openRawModal(kind) {{
      const titles = {{
        health: "Raw Health",
        overview: "Raw Overview",
        metrics: "Raw Metrics",
        files: "Raw File Inventory",
      }};
      document.getElementById("raw-modal-title").textContent = titles[kind] || "Raw Data";
      document.getElementById("raw-modal-content").textContent = rawPayloads[kind] || "";
      document.getElementById("raw-modal").showModal();
    }}
    function closeRawModal() {{
      document.getElementById("raw-modal").close();
    }}
    renderOverview(initialData);
    refreshKbOptions();
    refreshFiles();
    refreshMetrics();
    setInterval(() => {{
      refreshOverview();
      refreshMetrics();
      refreshFiles();
      refreshKbOptions();
    }}, 15000);
  </script>
</body>
</html>"""
