from __future__ import annotations

import contextvars
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

from bizrag.common.time_utils import utc_now


_trace_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "bizrag_trace_id",
    default=None,
)
_span_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "bizrag_span_id",
    default=None,
)


def current_trace_id() -> Optional[str]:
    return _trace_id_var.get()


def current_span_id() -> Optional[str]:
    return _span_id_var.get()


def ensure_trace_id() -> str:
    trace_id = current_trace_id()
    if trace_id:
        return trace_id
    trace_id = str(uuid.uuid4())
    _trace_id_var.set(trace_id)
    return trace_id


class ObservedOperation:
    def __init__(
        self,
        *,
        store: Any = None,
        component: str,
        operation: str,
        logger: Optional[logging.Logger] = None,
        kb_id: Optional[str] = None,
        task_id: Optional[str] = None,
        event_id: Optional[str] = None,
        source_uri: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._store = store
        self._logger = logger or logging.getLogger(f"bizrag.{component}")
        self.component = str(component)
        self.operation = str(operation)
        self.kb_id = kb_id
        self.task_id = task_id
        self.event_id = event_id
        self.source_uri = source_uri
        self.details: Dict[str, Any] = dict(details or {})
        self.trace_id: Optional[str] = None
        self.span_id: Optional[str] = None
        self.parent_span_id: Optional[str] = None
        self.started_at: Optional[str] = None
        self._perf_start: Optional[float] = None
        self._trace_token: Any = None
        self._span_token: Any = None
        self._finished = False

    def annotate(self, **details: Any) -> None:
        for key, value in details.items():
            if value is not None:
                self.details[key] = value

    def __enter__(self) -> "ObservedOperation":
        self.trace_id = current_trace_id() or str(uuid.uuid4())
        self.parent_span_id = current_span_id()
        self.span_id = str(uuid.uuid4())
        self.started_at = utc_now()
        self._perf_start = time.perf_counter()
        self._trace_token = _trace_id_var.set(self.trace_id)
        self._span_token = _span_id_var.set(self.span_id)
        if self._store is not None:
            self._store.create_operation_span(
                span_id=self.span_id,
                trace_id=self.trace_id,
                parent_span_id=self.parent_span_id,
                component=self.component,
                operation=self.operation,
                kb_id=self.kb_id,
                task_id=self.task_id,
                event_id=self.event_id,
                source_uri=self.source_uri,
                status="running",
                started_at=self.started_at,
                details=self.details,
            )
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        status = "failed" if exc is not None else "success"
        error_message = str(exc) if exc is not None else None
        self.finish(status=status, error_message=error_message)
        return False

    async def __aenter__(self) -> "ObservedOperation":
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return self.__exit__(exc_type, exc, tb)

    def finish(
        self,
        *,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        ended_at = utc_now()
        duration_ms = 0.0
        if self._perf_start is not None:
            duration_ms = max(0.0, (time.perf_counter() - self._perf_start) * 1000.0)

        payload = {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "component": self.component,
            "operation": self.operation,
            "kb_id": self.kb_id,
            "task_id": self.task_id,
            "event_id": self.event_id,
            "source_uri": self.source_uri,
            "status": status,
            "duration_ms": round(duration_ms, 3),
            "details": self.details,
        }
        if error_message:
            payload["error_message"] = error_message

        self._logger.info(json.dumps(payload, ensure_ascii=False, sort_keys=True))

        if self._store is not None and self.span_id is not None:
            self._store.finish_operation_span(
                span_id=self.span_id,
                status=status,
                ended_at=ended_at,
                duration_ms=duration_ms,
                details=self.details,
                error_message=error_message,
            )

        if self._span_token is not None:
            _span_id_var.reset(self._span_token)
        if self._trace_token is not None:
            _trace_id_var.reset(self._trace_token)


def observe_operation(
    *,
    store: Any = None,
    component: str,
    operation: str,
    logger: Optional[logging.Logger] = None,
    kb_id: Optional[str] = None,
    task_id: Optional[str] = None,
    event_id: Optional[str] = None,
    source_uri: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> ObservedOperation:
    return ObservedOperation(
        store=store,
        component=component,
        operation=operation,
        logger=logger,
        kb_id=kb_id,
        task_id=task_id,
        event_id=event_id,
        source_uri=source_uri,
        details=details,
    )
