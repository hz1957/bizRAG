# RAG Eval Workspace

This workspace is reserved for synthetic RAG evaluation data generation.

Layout:

- `hf_cache/`: Hugging Face hub and datasets cache
- `prepared/`: reusable source snapshots and chunk pools
- `generated/`: per-run QA candidates, final eval datasets, and run summaries
- `../scripts/export_bizrag_benchmark_dataset.py`: make a benchmark-ready JSONL with `question` + `golden_answers`
- `../scripts/run_bizrag_rag_eval.py`: run the current BizRAG `rag_eval` pipeline against a registered KB
- `run_m_ric_huggingface_doc.sh`: launcher for the `m-ric/huggingface_doc` source dataset using local Ollama `mistral:latest`
  Default dataset profile:
  - `core_factoid`: 70%
  - `cross_sentence`: 20% (generated from 2 adjacent chunks from the same source document)
  - `unanswerable`: 10%
  - `ambiguous_rewrite`: 0%
  Shared chunk settings for all subsets:
  - `chunk_size`: 600
  - `chunk_overlap`: 100
  The four subsets share the same chunk pool. `cross_sentence` differs by consuming two adjacent chunks; the others consume one chunk.
  Prepared artifacts are reused across later generation runs when the source and chunk config match.

Usage:

```bash
cd /Users/haoming.zhang/PyCharmMiscProject/bizRAG
./rag_eval_workspace/run_m_ric_huggingface_doc.sh
```

The reusable prepared dataset directory is:

- `rag_eval_workspace/prepared/m-ric_huggingface_doc`

The default generation output directory is:

- `rag_eval_workspace/generated/m-ric_huggingface_doc/<run-name>`

Benchmark Format

The current BizRAG `benchmark.get_data` loader expects:

- `question`
- `golden_answers`

where `golden_answers` is a list of acceptable answers, matching [benchmark/parameter.yaml](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/bizrag/servers/benchmark/parameter.yaml:1).

New generation runs now include:

- `question_id`
- `qid`
- `golden_answers`

If you want to retrofit an older `qa_eval_dataset.jsonl`, run:

```bash
cd /Users/haoming.zhang/PyCharmMiscProject/bizRAG
python scripts/export_bizrag_benchmark_dataset.py \
  --input rag_eval_workspace/generated/m-ric_huggingface_doc/<run-name>/qa_eval_dataset.jsonl \
  --output rag_eval_workspace/generated/m-ric_huggingface_doc/<run-name>/qa_eval_dataset.benchmark.jsonl
```

Recommended Metrics

For the current synthetic QA setup, use these as the primary metrics:

- Generation:
  - `acc`
  - `em`
  - `f1`
- Secondary generation metric:
  - `coverem`
- Retrieval, if you later prepare `run.txt` + `qrels.txt` for `evaluate_trec`:
  - `Recall@5`
  - `Recall@10`
  - `MRR`
  - `nDCG@10`

Use these more cautiously in the current setup:

- `stringem`
- `rouge-1`
- `rouge-2`
- `rouge-l`
- `map`
- `precision@k`

Reason:

- The current dataset is short-answer QA first, so `acc/em/f1` are more informative than ROUGE.
- Retrieval qrels are not fully materialized by default, so `map` and `precision@k` are more sensitive to incomplete relevance labeling.

How To Test Current BizRAG

1. Ensure the target KB is already ingested and indexed in the current BizRAG runtime.

2. Prepare a benchmark-ready dataset:

```bash
cd /Users/haoming.zhang/PyCharmMiscProject/bizRAG
python scripts/export_bizrag_benchmark_dataset.py \
  --input rag_eval_workspace/generated/m-ric_huggingface_doc/<run-name>/qa_eval_dataset.jsonl \
  --output rag_eval_workspace/generated/m-ric_huggingface_doc/<run-name>/qa_eval_dataset.benchmark.jsonl
```

3. Run the BizRAG `rag_eval` pipeline against a registered KB:

```bash
cd /Users/haoming.zhang/PyCharmMiscProject/bizRAG
python scripts/run_bizrag_rag_eval.py \
  --kb-id clinical_documents \
  --benchmark-path rag_eval_workspace/generated/m-ric_huggingface_doc/<run-name>/qa_eval_dataset.benchmark.jsonl \
  --metadata-db runtime/metadata.db \
  --metrics acc em f1 coverem \
  --top-k 5 \
  --generation-backend openai \
  --generation-model mistral:latest \
  --generation-base-url http://127.0.0.1:11434/v1 \
  --generation-api-key ollama \
  --save-path rag_eval_workspace/generated/bizrag_eval/clinical_documents/rag_eval_results.json
```

Notes:

- This path exercises the current [rag_eval.yaml](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/bizrag/pipelines/rag_eval.yaml:1) pipeline: benchmark -> retrieve -> rerank -> prompt -> generate -> evaluate.
- Replace `<run-name>` with the generated run directory under `rag_eval_workspace/generated/m-ric_huggingface_doc/`.
- The script resolves retriever / reranker runtime parameters from the registered KB, keeps retrieval depth aligned with KB defaults, applies `--top-k` as the final reranked top-k, and only overrides generation/eval settings explicitly passed on the CLI.
- If you only want to score already-generated predictions against gold answers, use [evaluate_results.yaml](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/bizrag/pipelines/evaluate_results.yaml:1) instead of `rag_eval`.
- If you want IR-only metrics like `MRR`, `Recall`, `Precision`, `MAP`, or `NDCG`, you need TREC-format `run.txt` and `qrels.txt`, then call [eval_trec.yaml](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/bizrag/pipelines/eval_trec.yaml:1).
