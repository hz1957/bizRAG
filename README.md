# bizRAG

`bizRAG` is a minimal integration project that uses the `ultrarag` Python package
while keeping the local files that the current SDK still expects:

- `servers/`
- `examples/*.yaml`
- `examples/parameter/*.yaml`
- `examples/server/*_server.yaml`

This layout matches the current UltraRAG SDK behavior:

- `PipelineCall(...)` needs local pipeline YAML and parameter YAML files
- `ToolCall.initialize(...)` needs a local `server_root`
- `ToolCall` also expects `servers/<name>/server.yaml`

## Install

```bash
pip install -e .
```

Editable install is recommended because the current SDK integration still reads local
`servers/` and `examples/` files from the repository.

The project depends on:

- `ultrarag[retriever,corpus]`

## Linux Notes

The current code path is expected to run on Linux. For Linux deployments, these
runtime dependencies are the important ones:

- `.doc` / `.wps`: install one of `libreoffice` / `soffice`, `antiword`, or `catdoc`
- `.xls`: `xlrd>=2.0.1`
- `.xlsx`: `openpyxl`
- Milvus Lite file-based local indexing still requires the process to have permission
  to create and lock the configured DB file

## Project Layout

```text
bizRAG/
  bizrag/
    src/
    pipelines/
    config/
```

## SDK Usage

### ToolCall

```python
from bizrag.sdk import initialize_toolcall, build_text_corpus, chunk_documents

initialize_toolcall(["corpus"])

build_text_corpus(
    parse_file_path="data/raw",
    text_corpus_save_path="data/corpus/text.jsonl",
)

chunk_documents(
    raw_chunk_path="data/corpus/text.jsonl",
    chunk_path="data/chunks/chunks.jsonl",
)
```

### PipelineCall

```python
from bizrag.sdk import run_named_pipeline

run_named_pipeline(
    "build_text_corpus",
    parameter_file="examples/parameter/build_text_corpus_parameter.yaml",
)
```

## Copied Files

The following UltraRAG resources were copied into this project:

- `servers/corpus`
- `servers/retriever`
- `examples/build_text_corpus.yaml`
- `examples/corpus_chunk.yaml`
- `examples/milvus_index.yaml`
- matching `examples/parameter/*`
- matching `examples/server/*`
- `docs/SDKReference.md`
- `docs/4BizAgentPlatform.md`

## Retrieve API

Phase 1 adds a BizAgent-facing retrieve service:

```bash
python -m bizrag.service.retrieve_api \
  --retriever-config bizrag/src/servers/retriever/parameter.yaml \
  --kb-registry bizrag/config/kb_registry.yaml
```

Example request:

```json
{
  "kb_id": "bizagent_contract",
  "query": "怎么申请合同审批",
  "top_k": 5,
  "filters": {
    "source_type": ["pdf", "docx"]
  }
}
```

The service exposes:

- `POST /api/v1/retrieve`
- `POST /api/v1/extract`
- `GET /healthz`

Example extract request:

```json
{
  "kb_id": "bizagent_contract",
  "query": "这个报价的总价是多少",
  "top_k": 5,
  "fields": [
    {
      "name": "total_price",
      "type": "number",
      "aliases": ["共计", "总价", "Total Cost"],
      "normalizers": ["currency"],
      "required": true
    }
  ]
}
```

## Docs

- BizAgent 平台接入与分阶段计划：[bizrag/docs/BizAgentPlatform.md](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/bizrag/docs/BizAgentPlatform.md:1)

## Evaluation

Phase 1 also vendors benchmark/evaluation servers and pipelines:

- `bizrag/pipelines/load_data.yaml`
- `bizrag/pipelines/evaluate_results.yaml`
- `bizrag/pipelines/eval_trec.yaml`
- `bizrag/pipelines/eval_trec_pvalue.yaml`
- `bizrag/pipelines/evaluate_structured_results.yaml`

## Knowledge Base Admin

Phase 2 adds a local KB admin entry for metadata storage, directory sync, document deletion,
and collection rebuild:

```bash
python -m bizrag.service.kb_admin \
  register-kb \
  --kb-id bizrag_bcrp \
  --retriever-config bizrag/config/retriever_phase1_local.yaml \
  --source-root raw_knowledge/真实案例
```

```bash
python -m bizrag.service.kb_admin \
  ingest-path \
  --kb-id bizrag_bcrp \
  --path raw_knowledge/真实案例/案例1 \
  --sync-deletions
```

The Phase 2 admin persists state in:

- `bizrag/state/metadata.db`
- `runtime/kbs/<kb_id>/...`

## Notes

- This is a source-style SDK integration, not a fully self-contained packaged SDK.
- If UltraRAG changes server signatures, the copied `server.yaml` files may need to
  be refreshed.
- `milvus_index` still requires a reachable Milvus instance and valid embedding
  backend configuration.
- In the current UltraRAG implementation, the copied `milvus_index` example is set
  to `is_demo: true` because that is the working path for Milvus indexing with
  document contents included.
