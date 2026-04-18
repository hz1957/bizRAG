from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional


def _decode_jsonish(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def iter_pipeline_output_values(result: Any, key: str) -> Iterable[Any]:
    if not isinstance(result, dict):
        return

    snapshots = result.get("all_results")
    if isinstance(snapshots, list):
        for snapshot in reversed(snapshots):
            if not isinstance(snapshot, dict):
                continue
            memory = snapshot.get("memory")
            if not isinstance(memory, dict):
                continue
            for candidate in (f"memory_{key}", key):
                if candidate in memory:
                    yield _decode_jsonish(memory[candidate])

    final_result = _decode_jsonish(result.get("final_result"))
    if isinstance(final_result, dict) and key in final_result:
        yield _decode_jsonish(final_result[key])

    if key in result:
        yield _decode_jsonish(result[key])

    for value in result.values():
        value = _decode_jsonish(value)
        if isinstance(value, dict) and key in value:
            yield _decode_jsonish(value[key])


def _coerce_retrieve_items(value: Any) -> Optional[List[Dict[str, Any]]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return None
    if not value:
        return []
    if all(isinstance(item, dict) for item in value):
        return [item for item in value if isinstance(item, dict)]

    nested_lists = [item for item in value if isinstance(item, list)]
    if not nested_lists:
        return None

    flattened = [
        item
        for sublist in nested_lists
        for item in sublist
        if isinstance(item, dict)
    ]
    if flattened:
        return flattened
    if any(not sublist for sublist in nested_lists):
        return []
    return None


def extract_retrieve_items(result: Any) -> List[Dict[str, Any]]:
    for value in iter_pipeline_output_values(result, "ret_items"):
        items = _coerce_retrieve_items(value)
        if items is not None:
            return items
    raise RuntimeError("pipeline did not return ret_items")


def extract_int_output(result: Any, key: str, *, default: int = 0) -> int:
    for value in iter_pipeline_output_values(result, key):
        if value is None:
            continue
        if isinstance(value, list):
            if not value:
                return default
            value = value[0]
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def extract_list_output(result: Any, key: str) -> List[Any]:
    for value in iter_pipeline_output_values(result, key):
        if value is None:
            continue
        if isinstance(value, list):
            return value
        return [value]
    raise RuntimeError(f"pipeline did not return {key}")


def extract_first_text_output(result: Any, key: str) -> str:
    values = extract_list_output(result, key)
    if not values:
        return ""
    return str(values[0] or "")
