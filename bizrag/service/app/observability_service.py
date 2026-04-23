from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional

from bizrag.common.time_utils import utc_now
from bizrag.infra.metadata_store import MetadataStore

ACTIVE_WORK_MAX_AGE = timedelta(minutes=10)


HEALTH_CHECKS: List[Dict[str, Any]] = [
    {
        "id": "metadata_store",
        "label": "Metadata Store",
        "description": "The metadata database backing KBs, documents, tasks, and operation spans.",
    },
    {
        "id": "read_runtime",
        "label": "Read Runtime",
        "description": "ReadService readiness and warmed pipeline sessions for retrieve/RAG requests.",
    },
    {
        "id": "rustfs_event_queue",
        "label": "RustFS Event Queue",
        "description": "Queued and running RustFS events persisted in metadata before worker processing.",
    },
]


MONITORED_COMPONENTS: List[Dict[str, Any]] = [
    {
        "id": "api",
        "label": "Read API",
        "description": "HTTP layer for /retrieve and /rag requests.",
    },
    {
        "id": "ingest",
        "label": "Ingest Coordinator",
        "description": "KBAdmin orchestration around file ingest and path sync.",
    },
    {
        "id": "corpus",
        "label": "Corpus Parse",
        "description": "Raw document parsing into intermediate corpus rows.",
    },
    {
        "id": "chunk",
        "label": "Chunk Build",
        "description": "Corpus chunking before indexing.",
    },
    {
        "id": "index",
        "label": "Index Build",
        "description": "Vector/BM25 indexing and collection rebuild operations.",
    },
    {
        "id": "queue",
        "label": "MQ Bridge / Event Intake",
        "description": "MQ bridge and event enqueue path from RabbitMQ/Kafka into RustFS events.",
    },
    {
        "id": "worker",
        "label": "RustFS Worker",
        "description": "Background worker that turns RustFS events into KB writes.",
    },
    {
        "id": "retrieve",
        "label": "Read Requests",
        "description": "Retrieve and RAG pipeline executions inside ReadService.",
    },
    {
        "id": "extract",
        "label": "Field Extraction",
        "description": "Structured extraction built on retrieved evidence.",
    },
    {
        "id": "admin",
        "label": "KB Admin",
        "description": "Administrative KB operations such as delete/rebuild.",
    },
]

COMPONENT_META: Dict[str, Dict[str, Any]] = {
    item["id"]: item for item in MONITORED_COMPONENTS
}
HEALTH_META: Dict[str, Dict[str, Any]] = {item["id"]: item for item in HEALTH_CHECKS}


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
        "description": "Read request p95 latency exceeds 3000 ms in the recent window.",
    },
    {
        "id": "extract_latency_high",
        "severity": "warning",
        "description": "Field extraction p95 latency exceeds 4000 ms in the recent window.",
    },
    {
        "id": "failed_operations_recent",
        "severity": "warning",
        "description": "One or more recent operations failed.",
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


def _component_meta(component_id: str) -> Dict[str, Any]:
    return COMPONENT_META.get(
        component_id,
        {
            "id": component_id,
            "label": component_id.replace("_", " ").title(),
            "description": "Observed operation component.",
        },
    )


def _health_meta(check_id: str) -> Dict[str, Any]:
    return HEALTH_META.get(
        check_id,
        {
            "id": check_id,
            "label": check_id.replace("_", " ").title(),
            "description": "",
        },
    )


def _status_rank(status: str) -> int:
    order = {
        "active": 0,
        "stalled": 1,
        "running": 2,
        "failed": 3,
        "cancelled": 4,
        "abandoned": 5,
        "success": 6,
        "queued": 7,
        "healthy": 8,
        "warning": 9,
        "degraded": 10,
        "idle": 11,
        "unknown": 12,
    }
    return order.get(str(status or "unknown"), 99)


def _row_sort_key(row: Dict[str, Any]) -> Any:
    ts = str(row.get("started_at") or row.get("created_at") or "")
    return (ts, -_status_rank(str(row.get("status") or "unknown")))


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


def _format_failure_sample(row: Dict[str, Any]) -> Dict[str, Any]:
    component = str(row.get("component") or "unknown")
    meta = _component_meta(component)
    return {
        "started_at": row.get("started_at"),
        "component": component,
        "component_label": meta["label"],
        "operation": row.get("operation"),
        "kb_id": row.get("kb_id"),
        "error_message": row.get("error_message"),
    }


def _row_activity_ts(row: Dict[str, Any]) -> Optional[datetime]:
    for key in ("updated_at", "started_at", "created_at"):
        ts = _parse_ts(str(row.get(key) or ""))
        if ts is not None:
            return ts
    return None


def _row_age_seconds(row: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[float]:
    activity_ts = _row_activity_ts(row)
    if activity_ts is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0.0, (current - activity_ts).total_seconds())


def _inflight_state(row: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[str]:
    status = str(row.get("status") or "").lower()
    if status not in {"running", "processing"}:
        return None
    age_seconds = _row_age_seconds(row, now=now)
    if age_seconds is None:
        return "active"
    return "stalled" if age_seconds > ACTIVE_WORK_MAX_AGE.total_seconds() else "active"


def _split_inflight_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    active: List[Dict[str, Any]] = []
    stalled: List[Dict[str, Any]] = []
    for row in rows:
        state = _inflight_state(row, now=now)
        if state == "active":
            active.append(row)
        elif state == "stalled":
            stalled.append(row)
    active.sort(key=_row_sort_key, reverse=True)
    stalled.sort(key=_row_sort_key, reverse=True)
    return {"active": active, "stalled": stalled}


def _enrich_operation_row(row: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    component = str(row.get("component") or "unknown")
    meta = _component_meta(component)
    enriched = dict(row)
    enriched["component_label"] = meta["label"]
    enriched["stage"] = _operation_stage(row)
    enriched["activity_state"] = _inflight_state(row, now=now) or str(row.get("status") or "unknown")
    enriched["age_seconds"] = _row_age_seconds(row, now=now)
    enriched["progress_items"] = _progress_items(row)
    return enriched


def _progress_items(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    details = dict(row.get("details_json") or {})
    items: List[Dict[str, Any]] = []

    def add(key: str, label: str, value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str) and not value.strip():
            return
        items.append({"key": key, "label": label, "value": value})

    if details.get("file_name"):
        add("file_name", "file", details.get("file_name"))
    if details.get("file_size_bytes") is not None:
        add("file_size_bytes", "file bytes", int(details.get("file_size_bytes") or 0))

    total_files = details.get("total_files")
    processed_files = details.get("processed_files")
    if total_files is not None:
        if processed_files is not None:
            add("processed_files", "files", f"{int(processed_files or 0)}/{int(total_files or 0)}")
        else:
            add("total_files", "files total", int(total_files or 0))

    total_bytes = details.get("total_bytes")
    processed_bytes = details.get("processed_bytes")
    if total_bytes is not None:
        if processed_bytes is not None:
            add("processed_bytes", "bytes", {"processed": int(processed_bytes or 0), "total": int(total_bytes or 0)})
        else:
            add("total_bytes", "bytes total", int(total_bytes or 0))

    add("corpus_rows", "corpus rows", details.get("corpus_rows"))
    add("corpus_characters", "corpus chars", details.get("corpus_characters"))
    add("chunk_rows", "chunks", details.get("chunk_rows"))
    add("chunk_characters", "chunk chars", details.get("chunk_characters"))
    add("created", "created", details.get("created"))
    add("updated", "updated", details.get("updated"))
    add("skipped", "skipped", details.get("skipped"))
    add("failed", "failed", details.get("failed"))
    add("deleted", "deleted", details.get("deleted"))
    add("index_mode", "index", details.get("index_mode"))
    return items


def _operation_stage(row: Dict[str, Any]) -> str:
    component = str(row.get("component") or "")
    operation = str(row.get("operation") or "")
    if component == "ingest":
        return "ingest"
    if component == "corpus":
        return "parse"
    if component == "chunk":
        return "chunk"
    if component == "index":
        if operation == "milvus_index":
            return "embedding/index"
        if operation == "bm25_index":
            return "bm25"
        if operation == "rebuild_kb":
            return "rebuild"
        return "index"
    if component == "queue":
        return "mq ingress"
    if component == "worker":
        return "worker"
    if component == "retrieve":
        if operation == "generate_answer":
            return "rag"
        return "retrieve"
    if component == "extract":
        return "extract"
    if component == "api":
        if operation == "rag_endpoint":
            return "rag api"
        return "retrieve api"
    if component == "admin":
        return "admin"
    return component or "unknown"


def _latest_completed_stage_rows(
    recent_rows: List[Dict[str, Any]],
    active_running_rows: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    active_sources = {
        str(row.get("source_uri") or "").strip()
        for row in active_running_rows
        if str(row.get("source_uri") or "").strip()
    }
    if not active_sources:
        return []

    completed: List[Dict[str, Any]] = []
    seen_stages = set()
    for row in sorted(recent_rows, key=_row_sort_key, reverse=True):
        if str(row.get("status") or "") != "success":
            continue
        source_uri = str(row.get("source_uri") or "").strip()
        if source_uri not in active_sources:
            continue
        stage = _operation_stage(row)
        if stage in {"mq ingress", "worker", "ingest", "retrieve", "rag", "retrieve api", "rag api", "admin"}:
            continue
        if stage in seen_stages:
            continue
        seen_stages.add(stage)
        completed.append(_enrich_operation_row(row, now=now))
        if len(completed) >= 6:
            break
    return completed


def _component_health_snapshot(
    component_id: str,
    rows: List[Dict[str, Any]],
    *,
    active_running_rows: Optional[List[Dict[str, Any]]] = None,
    stalled_running_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    meta = _component_meta(component_id)
    active_count = len(active_running_rows or [])
    stalled_count = len(stalled_running_rows or [])
    if not rows:
        status = "idle"
        detail = "No recent activity"
        if active_count:
            status = "active"
            detail = f"active={active_count} no recent completed spans"
        elif stalled_count:
            status = "stalled"
            detail = f"stalled={stalled_count} no recent completed spans"
        return {
            "id": component_id,
            "label": meta["label"],
            "description": meta["description"],
            "status": status,
            "detail": detail,
            "status_counts": {},
            "latency_ms": _latency_summary([]),
            "last_started_at": None,
            "latest_status": None,
            "running_count": active_count,
            "active_count": active_count,
            "stalled_count": stalled_count,
            "latest_operation": None,
        }

    ordered_rows = sorted(rows, key=_row_sort_key, reverse=True)
    status_counts = Counter(str(row.get("status") or "unknown") for row in ordered_rows)
    latest = ordered_rows[0]
    latest_status = str(latest.get("status") or "unknown")
    successful_rows = [row for row in ordered_rows if str(row.get("status") or "") == "success"]
    snapshot_status = "healthy"
    if active_count:
        snapshot_status = "active"
    elif stalled_count:
        snapshot_status = "stalled"
    elif latest_status == "failed" and not successful_rows:
        snapshot_status = "degraded"
    elif latest_status == "failed":
        snapshot_status = "warning"

    last_started_at = str(latest.get("started_at") or "")
    detail_bits = [f"last={latest_status}", f"total={len(rows)}"]
    if active_count:
        detail_bits.insert(0, f"active={active_count}")
    if stalled_count:
        detail_bits.insert(0, f"stalled={stalled_count}")
    detail = " ".join(detail_bits)
    return {
        "id": component_id,
        "label": meta["label"],
        "description": meta["description"],
        "status": snapshot_status,
        "detail": detail,
        "status_counts": dict(status_counts),
        "latency_ms": _latency_summary(ordered_rows),
        "last_started_at": last_started_at or None,
        "latest_status": latest_status,
        "running_count": active_count,
        "active_count": active_count,
        "stalled_count": stalled_count,
        "latest_operation": latest.get("operation"),
    }


class ObservabilityService:
    def __init__(self, *, store: MetadataStore) -> None:
        self._store = store

    def build_health_snapshot(self, *, read_service_status: str = "unknown") -> Dict[str, Any]:
        health_checks: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        try:
            self._store.count_kbs()
            metadata_ok = True
        except Exception as exc:
            metadata_ok = False
            meta = _health_meta("metadata_store")
            health_checks.append(
                {
                    "id": meta["id"],
                    "label": meta["label"],
                    "description": meta["description"],
                    "status": "down",
                    "detail": str(exc),
                }
            )
        else:
            meta = _health_meta("metadata_store")
            health_checks.append(
                {
                    "id": meta["id"],
                    "label": meta["label"],
                    "description": meta["description"],
                    "status": "healthy",
                    "detail": self._store.backend_name,
                }
            )

        meta = _health_meta("read_runtime")
        health_checks.append(
            {
                "id": meta["id"],
                "label": meta["label"],
                "description": meta["description"],
                "status": "healthy" if read_service_status == "ready" else "degraded",
                "detail": read_service_status,
            }
        )

        recent_rows = self._recent_operation_rows(window_minutes=30)
        running_rows = self._store.list_operation_spans(status="running", limit=200)
        running_split = _split_inflight_rows(running_rows, now=now)
        active_running_by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        stalled_running_by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in running_split["active"]:
            active_running_by_component[str(row.get("component") or "unknown")].append(row)
        for row in running_split["stalled"]:
            stalled_running_by_component[str(row.get("component") or "unknown")].append(row)
        queue_counts = self._store.count_rustfs_events_by_status()
        event_rows = self._store.list_rustfs_events(limit=400)
        inflight_events = _split_inflight_rows(event_rows, now=now)
        queued = int(queue_counts.get("queued") or 0)
        active_processing = len(inflight_events["active"])
        stalled_processing = len(inflight_events["stalled"])
        queue_status = "healthy"
        if queued > 100:
            queue_status = "degraded"
        elif stalled_processing:
            queue_status = "stalled"
        meta = _health_meta("rustfs_event_queue")
        queue_bits = [f"queued={queued}", f"active={active_processing}"]
        if stalled_processing:
            queue_bits.append(f"stalled={stalled_processing}")
        health_checks.append(
            {
                "id": meta["id"],
                "label": meta["label"],
                "description": meta["description"],
                "status": queue_status,
                "detail": " ".join(queue_bits),
            }
        )

        by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in recent_rows:
            by_component[str(row.get("component") or "unknown")].append(row)

        for component in MONITORED_COMPONENTS:
            component_id = component["id"]
            snapshot = _component_health_snapshot(
                component_id,
                by_component.get(component_id, []),
                active_running_rows=active_running_by_component.get(component_id, []),
                stalled_running_rows=stalled_running_by_component.get(component_id, []),
            )
            health_checks.append(
                {
                    "id": component_id,
                    "label": component["label"],
                    "description": component["description"],
                    "status": snapshot["status"],
                    "detail": snapshot["detail"],
                }
            )

        status = "ok"
        if not metadata_ok:
            status = "down"
        elif any(item["status"] in {"degraded", "warning", "stalled"} for item in health_checks):
            status = "degraded"
        elif any(item["status"] == "active" for item in health_checks):
            status = "ok"
        return {
            "status": status,
            "generated_at": utc_now(),
            "checks": health_checks,
        }

    def _build_kb_activity(
        self,
        *,
        recent_rows: List[Dict[str, Any]],
        active_running_rows: List[Dict[str, Any]],
        stalled_running_rows: List[Dict[str, Any]],
        now: datetime,
    ) -> List[Dict[str, Any]]:
        kb_rows = self._store.list_kbs()
        by_kb_recent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        by_kb_active: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        by_kb_stalled: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in recent_rows:
            kb_id = str(row.get("kb_id") or "").strip()
            if kb_id:
                by_kb_recent[kb_id].append(row)
        for row in active_running_rows:
            kb_id = str(row.get("kb_id") or "").strip()
            if kb_id:
                by_kb_active[kb_id].append(row)
        for row in stalled_running_rows:
            kb_id = str(row.get("kb_id") or "").strip()
            if kb_id:
                by_kb_stalled[kb_id].append(row)

        items: List[Dict[str, Any]] = []
        for kb in kb_rows:
            kb_id = str(kb.get("kb_id") or "")
            docs_by_status = self._store.count_documents_by_status(kb_id)
            tasks_by_status = self._store.count_tasks_by_status(kb_id)
            events_by_status = self._store.count_rustfs_events_by_status(kb_id)
            task_rows = self._store.list_tasks(kb_id=kb_id, limit=200)
            event_rows = self._store.list_rustfs_events(kb_id=kb_id, limit=200)
            task_inflight = _split_inflight_rows(task_rows, now=now)
            event_inflight = _split_inflight_rows(event_rows, now=now)
            recent = sorted(by_kb_recent.get(kb_id, []), key=_row_sort_key, reverse=True)
            active_running = sorted(by_kb_active.get(kb_id, []), key=_row_sort_key, reverse=True)
            stalled_running = sorted(by_kb_stalled.get(kb_id, []), key=_row_sort_key, reverse=True)
            latest = recent[0] if recent else None
            latest_failure = next(
                (row for row in recent if str(row.get("status") or "") == "failed"),
                None,
            )
            completed_stages = _latest_completed_stage_rows(recent, active_running, now=now)
            current_stages = []
            seen_stages = set()
            for row in active_running:
                stage = _operation_stage(row)
                if stage in seen_stages:
                    continue
                seen_stages.add(stage)
                current_stages.append(stage)
            items.append(
                {
                    "kb_id": kb_id,
                    "collection_name": kb.get("collection_name"),
                    "documents_by_status": docs_by_status,
                    "tasks_by_status": tasks_by_status,
                    "rustfs_events_by_status": events_by_status,
                    "active_count": len(active_running),
                    "stalled_count": len(stalled_running),
                    "running_count": len(active_running),
                    "current_stages": current_stages,
                    "task_activity": {
                        "active": len(task_inflight["active"]),
                        "stalled": len(task_inflight["stalled"]),
                    },
                    "event_activity": {
                        "queued": int(events_by_status.get("queued") or 0),
                        "active": len(event_inflight["active"]),
                        "stalled": len(event_inflight["stalled"]),
                    },
                    "live_operations": [
                        _enrich_operation_row(row, now=now) for row in active_running[:8]
                    ],
                    "recent_completed_stages": completed_stages,
                    "stalled_operations": [
                        _enrich_operation_row(row, now=now) for row in stalled_running[:8]
                    ],
                    "latest_activity": {
                        "started_at": latest.get("started_at"),
                        "component": latest.get("component"),
                        "component_label": _component_meta(str(latest.get("component") or "")).get("label"),
                        "operation": latest.get("operation"),
                        "status": latest.get("status"),
                        "duration_ms": latest.get("duration_ms"),
                    } if latest else None,
                    "latest_failure": _format_failure_sample(latest_failure) if latest_failure else None,
                }
            )

        items.sort(
            key=lambda item: (
                0 if item["active_count"] else 1,
                -int(item["active_count"] or 0),
                -int(item["stalled_count"] or 0),
                str((item.get("latest_activity") or {}).get("started_at") or ""),
                item["kb_id"],
            ),
            reverse=False,
        )
        return items

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
                {
                    "rule_id": "queue_backlog_critical",
                    "severity": "critical",
                    "value": queued,
                    "title": "RustFS event backlog is critical",
                    "message": f"{queued} events are still queued in rustfs_events.",
                }
            )
        elif queued > 20:
            alerts.append(
                {
                    "rule_id": "queue_backlog_high",
                    "severity": "warning",
                    "value": queued,
                    "title": "RustFS event backlog is growing",
                    "message": f"{queued} events are currently queued in rustfs_events.",
                }
            )

        failed_rows = [row for row in rows if str(row.get("status")) == "failed"]
        if failed_rows:
            failed_by_component = Counter(str(row.get("component") or "unknown") for row in failed_rows)
            failed_by_kb = Counter(str(row.get("kb_id") or "system") for row in failed_rows)
            top_components = ", ".join(
                f"{_component_meta(component)['label']}={count}"
                for component, count in failed_by_component.most_common(3)
            )
            top_kbs = ", ".join(
                f"{kb_id}={count}"
                for kb_id, count in failed_by_kb.most_common(3)
            )
            alerts.append(
                {
                    "rule_id": "failed_operations_recent",
                    "severity": "warning",
                    "value": len(failed_rows),
                    "title": "Recent failed operations detected",
                    "message": (
                        f"{len(failed_rows)} failed operations in the recent window. "
                        f"Top components: {top_components or 'n/a'}. "
                        f"Top KBs: {top_kbs or 'n/a'}."
                    ),
                    "samples": [_format_failure_sample(row) for row in failed_rows[:5]],
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
                    "title": "Read requests are slower than expected",
                    "message": f"Read request p95 latency is {round(retrieve_p95, 1)} ms.",
                }
            )
        if extract_p95 > 4000:
            alerts.append(
                {
                    "rule_id": "extract_latency_high",
                    "severity": "warning",
                    "value": extract_p95,
                    "title": "Field extraction is slower than expected",
                    "message": f"Field extraction p95 latency is {round(extract_p95, 1)} ms.",
                }
            )

        worker_successes = [
            row
            for row in by_component.get("worker", [])
            if str(row.get("status")) == "success"
        ]
        worker_active = [
            row
            for row in self._store.list_operation_spans(status="running", limit=200)
            if str(row.get("component") or "") == "worker"
            and _inflight_state(row, now=datetime.now(timezone.utc)) == "active"
        ]
        last_worker_success = None
        if worker_successes:
            last_worker_success = _parse_ts(str(worker_successes[0].get("started_at") or ""))
        if queued > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
            if not worker_active and (last_worker_success is None or last_worker_success < cutoff):
                alerts.append(
                    {
                        "rule_id": "worker_stalled",
                        "severity": "critical",
                        "value": queued,
                        "title": "Worker appears stalled",
                        "message": (
                            f"{queued} queued events exist, but no successful worker activity "
                            "has been seen in the last 10 minutes."
                        ),
                        "last_worker_success_at": last_worker_success.isoformat() if last_worker_success else None,
                        "worker_active_count": len(worker_active),
                    }
                )
        return alerts

    def build_overview(self, *, read_service_status: str = "unknown") -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        recent_rows = self._recent_operation_rows()
        running_rows = self._store.list_operation_spans(status="running", limit=200)
        running_split = _split_inflight_rows(running_rows, now=now)
        active_running_rows = running_split["active"]
        stalled_running_rows = running_split["stalled"]
        by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in recent_rows:
            by_component[str(row.get("component") or "unknown")].append(row)
        active_running_by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        stalled_running_by_component: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in active_running_rows:
            active_running_by_component[str(row.get("component") or "unknown")].append(row)
        for row in stalled_running_rows:
            stalled_running_by_component[str(row.get("component") or "unknown")].append(row)

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
            snapshot = _component_health_snapshot(
                component,
                rows,
                active_running_rows=active_running_by_component.get(component, []),
                stalled_running_rows=stalled_running_by_component.get(component, []),
            )
            component_metrics[component] = snapshot

        inventory_documents = self._store.count_documents_by_status()
        inventory_tasks = self._store.count_tasks_by_status()
        inventory_events = self._store.count_rustfs_events_by_status()
        overview = {
            "generated_at": utc_now(),
            "health": self.build_health_snapshot(read_service_status=read_service_status),
            "inventory": {
                "kbs_total": self._store.count_kbs(),
                "documents_by_status": inventory_documents,
                "tasks_by_status": inventory_tasks,
                "rustfs_events_by_status": inventory_events,
                "documents_total": sum(int(value or 0) for value in inventory_documents.values()),
                "documents_active": int(inventory_documents.get("active") or 0),
                "running_operations": len(active_running_rows),
                "stalled_operations": len(stalled_running_rows),
                "queued_events": int(inventory_events.get("queued") or 0),
            },
            "components": component_metrics,
            "alerts": self._build_alerts(recent_rows),
            "kb_activity": self._build_kb_activity(
                recent_rows=recent_rows,
                active_running_rows=active_running_rows,
                stalled_running_rows=stalled_running_rows,
                now=now,
            ),
            "running_operations": [
                _enrich_operation_row(row, now=now)
                for row in active_running_rows
            ],
            "stalled_operations": [
                _enrich_operation_row(row, now=now)
                for row in stalled_running_rows
            ],
            "recent_spans": [_enrich_operation_row(row) for row in recent_rows[:100]],
            "alert_rules": ALERT_RULES,
            "stale_after_seconds": int(ACTIVE_WORK_MAX_AGE.total_seconds()),
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
                f'bizrag_component_health{{component="{check["id"]}",status="{check["status"]}"}} 1'
            )
        lines.append(f'bizrag_alerts_total {len(overview["alerts"])}')
        return "\n".join(lines) + "\n"
