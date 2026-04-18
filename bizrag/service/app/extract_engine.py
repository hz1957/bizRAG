from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


NUMBER_PATTERN = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?")
CURRENCY_PATTERN = re.compile(r"(?:[¥￥$]|RMB|USD)?\s*([-+]?\d[\d,]*(?:\.\d+)?)")
BOOLEAN_TRUE = {"true", "yes", "y", "1", "是", "有", "支持"}
BOOLEAN_FALSE = {"false", "no", "n", "0", "否", "无", "不支持"}


@dataclass
class Candidate:
    value: Any
    raw_value: str
    score: float
    evidence_index: int
    segment: str
    reason: str


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def _split_segments(content: str) -> List[str]:
    if not content:
        return []

    segments: List[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = re.split(r"[；;]\s*", stripped)
        for part in parts:
            piece = part.strip()
            if piece:
                segments.append(piece)

    if not segments and content.strip():
        segments.append(content.strip())
    return segments


def _unique(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(cleaned)
    return out


def _field_aliases(field: Dict[str, Any]) -> List[str]:
    aliases = [str(field.get("name") or "")]
    aliases.extend(str(alias) for alias in (field.get("aliases") or []))
    if field.get("description"):
        aliases.append(str(field["description"]))
    return _unique(aliases)


def _extract_key_value(segment: str) -> Tuple[Optional[str], Optional[str]]:
    match = re.match(r"(?P<key>[^=:：]+)\s*[:=：]\s*(?P<value>.+)", segment)
    if not match:
        return None, None
    return match.group("key").strip(), match.group("value").strip()


def _extract_after_alias(alias: str, segment: str) -> str:
    lowered = segment.lower()
    alias_lower = alias.lower()
    index = lowered.find(alias_lower)
    if index < 0:
        return ""

    tail = segment[index + len(alias) :].lstrip(":=： \t")
    if not tail:
        return ""

    if re.match(r"^[A-Za-z0-9_\u4e00-\u9fff（）()/-]{1,30}\s*[:：=]", tail):
        return ""

    next_label = re.search(r"\s+[A-Za-z0-9_\u4e00-\u9fff（）()/-]{1,30}\s*[:：=]", tail)
    if next_label:
        tail = tail[: next_label.start()]

    tail = re.split(r"[；;\n]", tail, maxsplit=1)[0].strip()
    return tail


def _coerce_value(
    field: Dict[str, Any],
    raw_value: str,
) -> Tuple[Any, str]:
    field_type = str(field.get("type") or "string").lower()
    normalizers = {str(item).lower() for item in (field.get("normalizers") or [])}

    if field_type == "boolean":
        lowered = raw_value.strip().lower()
        if lowered in BOOLEAN_TRUE:
            return True, raw_value
        if lowered in BOOLEAN_FALSE:
            return False, raw_value
        return None, raw_value

    if field_type in {"number", "integer"} or "currency" in normalizers:
        pattern = CURRENCY_PATTERN if "currency" in normalizers else NUMBER_PATTERN
        match = pattern.search(raw_value)
        if not match:
            return None, raw_value
        text_value = match.group(1) if match.lastindex else match.group(0)
        numeric_text = text_value.replace(",", "").strip()
        if field_type == "integer":
            try:
                return int(float(numeric_text)), raw_value
            except ValueError:
                return None, raw_value
        try:
            return float(numeric_text), raw_value
        except ValueError:
            return None, raw_value

    if field_type == "enum":
        enum_values = [str(v) for v in (field.get("enum_values") or [])]
        lowered = raw_value.lower()
        for value in enum_values:
            if value.lower() in lowered:
                return value, raw_value
        return None, raw_value

    return raw_value.strip(), raw_value


def _extract_candidate_from_segment(
    field: Dict[str, Any],
    aliases: List[str],
    segment: str,
    evidence_index: int,
) -> Optional[Candidate]:
    segment_lower = segment.lower()
    alias_matches = [alias for alias in aliases if alias.lower() in segment_lower]
    patterns = [str(p) for p in (field.get("patterns") or [])]
    score = 0.0
    if alias_matches:
        score += 3.0 + min(len(alias_matches), 2)

    extracted_value: Any = None
    raw_value = ""
    reason_parts: List[str] = []

    if alias_matches:
        for alias in alias_matches:
            alias_tail = _extract_after_alias(alias, segment)
            if not alias_tail:
                continue
            extracted_value, raw_value = _coerce_value(field, alias_tail)
            if extracted_value is not None:
                score += 4.0
                reason_parts.append("alias_tail")
                break

    for pattern in patterns:
        match = re.search(pattern, segment, flags=re.IGNORECASE)
        if not match:
            continue
        score += 5.0
        extracted_text = match.group(1) if match.lastindex else match.group(0)
        extracted_value, raw_value = _coerce_value(field, extracted_text)
        reason_parts.append(f"pattern:{pattern}")
        break

    if extracted_value is None:
        key, value = _extract_key_value(segment)
        if value is not None:
            key_lower = (key or "").lower()
            key_alias_match = any(
                alias.lower() in key_lower
                and len(key_lower) <= len(alias) + 6
                for alias in aliases
            )
            if key_alias_match:
                extracted_value, raw_value = _coerce_value(field, value)
                score += 2.5
                reason_parts.append("key_value")

    if extracted_value is None:
        field_type = str(field.get("type") or "string").lower()
        allow_segment_fallback = (
            not alias_matches
            or field_type != "string"
        )
        if allow_segment_fallback:
            extracted_value, raw_value = _coerce_value(field, segment)
        if extracted_value is not None and alias_matches:
            score += 1.5
            reason_parts.append("segment_value")

    if extracted_value is None:
        return None

    enum_values = [str(v) for v in (field.get("enum_values") or [])]
    if enum_values and isinstance(extracted_value, str):
        lowered = extracted_value.lower()
        if any(item.lower() in lowered for item in enum_values):
            score += 1.0

    if alias_matches:
        reason_parts.append(f"alias:{alias_matches[0]}")

    return Candidate(
        value=extracted_value,
        raw_value=_normalize_text(raw_value),
        score=score,
        evidence_index=evidence_index,
        segment=segment,
        reason=",".join(reason_parts) if reason_parts else "coerced",
    )


def extract_fields(
    *,
    fields: List[Dict[str, Any]],
    evidence_items: List[Dict[str, Any]],
    max_evidence_per_field: int = 2,
) -> Dict[str, Any]:
    field_results: List[Dict[str, Any]] = []
    output: Dict[str, Any] = {}
    evidence_indexes = set()

    for field in fields:
        field_name = str(field.get("name") or "").strip()
        if not field_name:
            continue
        aliases = _field_aliases(field)
        candidates: List[Candidate] = []

        for evidence_index, item in enumerate(evidence_items):
            segments = _split_segments(_normalize_text(item.get("content")))
            for segment in segments:
                candidate = _extract_candidate_from_segment(
                    field=field,
                    aliases=aliases,
                    segment=segment,
                    evidence_index=evidence_index,
                )
                if candidate is not None:
                    candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                item.score,
                -item.evidence_index,
                -len(item.raw_value),
            ),
            reverse=True,
        )

        if candidates:
            best = candidates[0]
            selected_indexes = []
            for candidate in candidates:
                if candidate.evidence_index in selected_indexes:
                    continue
                selected_indexes.append(candidate.evidence_index)
                if len(selected_indexes) >= max_evidence_per_field:
                    break

            evidence = [evidence_items[idx] for idx in selected_indexes]
            for idx in selected_indexes:
                evidence_indexes.add(idx)
            field_result = {
                "name": field_name,
                "value": best.value,
                "raw_value": best.raw_value,
                "status": "filled",
                "confidence": min(1.0, round(best.score / 10.0, 4)),
                "reason": best.reason,
                "evidence": evidence,
            }
            output[field_name] = best.value
        else:
            field_result = {
                "name": field_name,
                "value": None,
                "raw_value": None,
                "status": "missing",
                "confidence": 0.0,
                "reason": "no_match",
                "evidence": [],
            }
            output[field_name] = None

        field_results.append(field_result)

    citations = [evidence_items[idx] for idx in sorted(evidence_indexes)]
    required_missing = [
        field_result["name"]
        for field_result, field in zip(field_results, fields)
        if field.get("required") and field_result["status"] != "filled"
    ]
    status = "success"
    if required_missing and len(required_missing) == len(
        [field for field in fields if field.get("required")]
    ):
        status = "no_answer"
    elif required_missing:
        status = "partial"

    return {
        "result": output,
        "field_results": field_results,
        "citations": citations,
        "status": status,
        "missing_required_fields": required_missing,
    }
