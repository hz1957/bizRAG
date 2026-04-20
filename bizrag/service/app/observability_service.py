from __future__ import annotations

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
    detail = f"last={latest_status} total={len(rows)}"
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

    def _recent_operation_rows(
        self, *, limit: int = 400, window_minutes: int = 60
    ) -> List[Dict[str, Any]]:
        rows = self._store.list_operation_spans(limit=limit)
        return _recent_items(rows, minutes=window_minutes)

    def _build_alerts(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []
        queue_counts = self._store.count_rustfs_events_by_status()
        queued = int(queue_counts.get("queued") or 0)
        if queued > 100:
            alerts.append(
                {"rule_id": "queue_backlog_critical", "severity": "critical", "value": queued}
            )
        elif queued > 20:
            alerts.append(
                {"rule_id": "queue_backlog_high", "severity": "warning", "value": queued}
            )

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
        ordered_components = [component["id"] for component in MONITORED_COMPONENTS] + sorted(
            component for component in by_component.keys() if component not in {c["id"] for c in MONITORED_COMPONENTS}
        )
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
        lines.append(f'bizrag_health_status{{status="{overview["health"]["status"]}"}} 1')
        for check in overview["health"]["checks"]:
            lines.append(
                f'bizrag_component_health{{component="{check["name"]}",status="{check["status"]}"}} 1'
            )
        lines.append(f'bizrag_alerts_total {len(overview["alerts"])}')
        return "\n".join(lines) + "\n"
