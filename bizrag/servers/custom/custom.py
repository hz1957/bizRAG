import re
from typing import Any, Dict, List, Optional

from ultrarag.server import UltraRAG_MCP_Server

app = UltraRAG_MCP_Server("custom")


@app.tool(
    output=(
        "query,top_k,query_instruction,filters,output_fields,retriever_top_k,"
        "retriever_query_instruction->query_list,q_ls,retrieval_top_k,"
        "reranker_top_k,merge_top_k,query_instruction,filters,output_fields"
    )
)
def build_classic_read_inputs(
    query: str,
    top_k: int = 5,
    query_instruction: str = "",
    filters: Optional[Dict[str, Any]] = None,
    output_fields: Optional[List[str]] = None,
    retriever_top_k: int = 5,
    retriever_query_instruction: str = "",
) -> Dict[str, Any]:
    normalized_query = str(query or "")
    try:
        requested_top_k = int(top_k)
    except (TypeError, ValueError):
        requested_top_k = 5
    if requested_top_k <= 0:
        requested_top_k = 5

    try:
        candidate_top_k = int(retriever_top_k)
    except (TypeError, ValueError):
        candidate_top_k = requested_top_k
    if candidate_top_k <= 0:
        candidate_top_k = requested_top_k

    candidate_top_k = max(candidate_top_k, requested_top_k)
    effective_instruction = str(query_instruction or retriever_query_instruction or "")
    normalized_filters = dict(filters or {})
    normalized_output_fields = list(output_fields or [])
    query_list = [normalized_query]
    return {
        "query_list": query_list,
        "q_ls": query_list,
        "retrieval_top_k": candidate_top_k,
        "reranker_top_k": requested_top_k,
        "merge_top_k": candidate_top_k * 2,
        "query_instruction": effective_instruction,
        "filters": normalized_filters,
        "output_fields": normalized_output_fields,
    }


def _item_key(item: Dict[str, Any], index: int) -> str:
    # Deduplicate at chunk granularity first. Using doc_id here collapses all
    # chunks from the same document into a single hit after dense/sparse fusion.
    for field in ("vector_id", "chunk_id", "id", "doc_id", "source_uri"):
        value = item.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    return f"content:{item.get('content', '')}:{index}"


def _coerce_score(item: Dict[str, Any]) -> Optional[float]:
    value = item.get("score")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _merge_item_fields(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if value in (None, "", []):
            continue
        if merged.get(key) in (None, "", []):
            merged[key] = value
    return merged


def _normalized_scores(row: List[Dict[str, Any]]) -> List[float]:
    raw_scores = [_coerce_score(item) for item in row]
    valid_scores = [score for score in raw_scores if score is not None]
    if not valid_scores:
        return [1.0 / float(rank + 1) for rank in range(len(row))]

    min_score = min(valid_scores)
    max_score = max(valid_scores)
    if max_score <= min_score:
        return [1.0 if score is not None else 0.0 for score in raw_scores]

    normalized: List[float] = []
    for score in raw_scores:
        if score is None:
            normalized.append(0.0)
        else:
            normalized.append((score - min_score) / (max_score - min_score))
    return normalized


def _fuse_rows(
    primary_row: List[Dict[str, Any]],
    secondary_row: List[Dict[str, Any]],
    *,
    top_k: int,
    strategy: str,
    rrf_k: int,
    primary_weight: float,
    secondary_weight: float,
) -> List[Dict[str, Any]]:
    strategy = str(strategy or "rrf").strip().lower()
    if strategy not in {"rrf", "normalized", "normalized_score"}:
        raise ValueError(
            "[custom] strategy must be one of: rrf, normalized, normalized_score"
        )

    primary_norm = _normalized_scores(primary_row) if strategy != "rrf" else []
    secondary_norm = _normalized_scores(secondary_row) if strategy != "rrf" else []

    fused: Dict[str, Dict[str, Any]] = {}

    def _append_row(
        row: List[Dict[str, Any]],
        *,
        source_name: str,
        weight: float,
        normalized_scores: List[float],
    ) -> None:
        for rank, item in enumerate(row):
            key = _item_key(item, rank)
            entry = fused.get(key)
            if entry is None:
                entry = {
                    "item": dict(item),
                    "score": 0.0,
                    "sources": [],
                }
                fused[key] = entry
            else:
                entry["item"] = _merge_item_fields(entry["item"], item)

            if strategy == "rrf":
                contribution = float(weight) / float(max(1, int(rrf_k)) + rank + 1)
            else:
                contribution = float(weight) * float(normalized_scores[rank])

            entry["score"] += contribution
            if source_name not in entry["sources"]:
                entry["sources"].append(source_name)

            raw_score = _coerce_score(item)
            if raw_score is not None:
                entry["item"][f"{source_name}_score"] = raw_score
            if strategy != "rrf":
                entry["item"][f"{source_name}_normalized_score"] = float(
                    normalized_scores[rank]
                )

    _append_row(
        primary_row,
        source_name="dense",
        weight=primary_weight,
        normalized_scores=primary_norm,
    )
    _append_row(
        secondary_row,
        source_name="sparse",
        weight=secondary_weight,
        normalized_scores=secondary_norm,
    )

    ranked = sorted(
        fused.values(),
        key=lambda value: float(value["score"]),
        reverse=True,
    )

    merged_row: List[Dict[str, Any]] = []
    for value in ranked[: max(0, int(top_k))]:
        item = dict(value["item"])
        item["fusion_score"] = float(value["score"])
        item["score"] = float(value["score"])
        item["retrieval_sources"] = list(value["sources"])
        item["fusion_strategy"] = strategy
        merged_row.append(item)
    return merged_row


@app.tool(
    output="ret_items,temp_items,top_k,strategy,rrf_k,primary_weight,secondary_weight->ret_items"
)
def merge_retrieve_items(
    ret_items: List[List[Dict[str, Any]]],
    temp_items: List[List[Dict[str, Any]]],
    top_k: int = 10,
    strategy: str = "rrf",
    rrf_k: int = 60,
    primary_weight: float = 1.0,
    secondary_weight: float = 1.0,
) -> Dict[str, List[List[Dict[str, Any]]]]:
    def _normalize_rows(rows: Any) -> List[List[Dict[str, Any]]]:
        if rows in (None, ""):
            return []
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            return [rows]
        return [list(row or []) for row in list(rows or [])]

    primary_rows = _normalize_rows(ret_items)
    secondary_rows = _normalize_rows(temp_items)
    if not primary_rows and not secondary_rows:
        return {"ret_items": []}
    max_rows = max(len(primary_rows), len(secondary_rows))
    while len(primary_rows) < max_rows:
        primary_rows.append([])
    while len(secondary_rows) < max_rows:
        secondary_rows.append([])

    merged_rows = [
        _fuse_rows(
            primary_row,
            secondary_row,
            top_k=top_k,
            strategy=strategy,
            rrf_k=rrf_k,
            primary_weight=primary_weight,
            secondary_weight=secondary_weight,
        )
        for primary_row, secondary_row in zip(primary_rows, secondary_rows)
    ]
    return {"ret_items": merged_rows}


def _format_retrieve_item(item: Dict[str, Any], rank: int) -> str:
    def _strip_chunk_wrappers(text: Any) -> str:
        value = str(text or "").strip()
        if not value:
            return ""
        match = re.match(r"^Title:\n.*?\n\nContent:\n(.*)$", value, flags=re.DOTALL)
        if match:
            return match.group(1).strip()
        return value

    file_name = str(item.get("file_name") or "").strip()
    sheet_name = str(item.get("sheet_name") or "").strip()
    row_index = item.get("row_index")
    source_uri = str(item.get("source_uri") or "").strip()
    title = str(item.get("title") or item.get("file_name") or f"Result {rank}").strip()
    content = _strip_chunk_wrappers(item.get("content"))

    source_parts: List[str] = []
    if file_name:
        source_parts.append(f"File: {file_name}")
    elif title:
        source_parts.append(f"Title: {title}")
    if sheet_name:
        source_parts.append(f"Sheet: {sheet_name}")
    if row_index not in (None, ""):
        source_parts.append(f"Row: {row_index}")
    if source_uri:
        source_parts.append(f"Source: {source_uri}")

    lines = []
    if source_parts:
        lines.append(" | ".join(source_parts))
    if content:
        lines.append(content)
    return "\n".join(lines).strip()


@app.tool(output="ret_items->ret_psg")
def retrieve_items_to_passages(
    ret_items: Any,
) -> Dict[str, List[List[str]]]:
    if not ret_items:
        return {"ret_psg": [[]]}

    if isinstance(ret_items, list) and ret_items and isinstance(ret_items[0], dict):
        normalized_rows = [ret_items]
    else:
        normalized_rows = list(ret_items)

    rows: List[List[str]] = []
    for row in normalized_rows:
        rows.append(
            [
                _format_retrieve_item(item, rank + 1)
                for rank, item in enumerate(row)
            ]
        )
    return {"ret_psg": rows}


@app.tool(output="ans_ls->pred_ls")
def output_extract_from_boxed(ans_ls: List[str]) -> Dict[str, List[str]]:
    def extract(ans: str) -> str:
        start = ans.rfind(r"\boxed{")
        if start == -1:
            return ans.strip()

        i = start + len(r"\boxed{")
        brace_level = 1
        end = i
        while end < len(ans) and brace_level > 0:
            if ans[end] == "{":
                brace_level += 1
            elif ans[end] == "}":
                brace_level -= 1
            end += 1

        content = ans[i : end - 1].strip()
        content = re.sub(r"^\$+|\$+$", "", content).strip()
        content = re.sub(r"^\\\(|\\\)$", "", content).strip()
        if content.startswith(r"\text{") and content.endswith("}"):
            content = content[len(r"\text{") : -1].strip()
        return content.strip("()").strip()

    return {"pred_ls": [extract(str(ans)) for ans in ans_ls]}


if __name__ == "__main__":
    app.run(transport="stdio")
