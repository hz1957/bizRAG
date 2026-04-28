#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def stable_payload_hash(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a generated QA eval dataset into benchmark-ready JSONL for BizRAG."
    )
    parser.add_argument("--input", required=True, help="Input QA dataset JSONL path")
    parser.add_argument("--output", required=True, help="Output benchmark JSONL path")
    return parser.parse_args()


def build_question_id(row: dict[str, Any]) -> str:
    existing = str(row.get("question_id") or row.get("qid") or "").strip()
    if existing:
        return existing
    return stable_payload_hash(
        {
            "question": row.get("question"),
            "answer": row.get("answer"),
            "subset_name": row.get("subset_name"),
            "source_doc": row.get("source_doc"),
            "context_chunk_start_indexes": row.get("context_chunk_start_indexes"),
        }
    )


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8") as src, output_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as dst:
        for line in src:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            answer = str(row.get("answer") or "")
            golden_answers = row.get("golden_answers")
            if not isinstance(golden_answers, list) or not golden_answers:
                golden_answers = [answer]

            question_id = build_question_id(row)
            row["question_id"] = question_id
            row["qid"] = question_id
            row["golden_answers"] = [str(item) for item in golden_answers]
            dst.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
