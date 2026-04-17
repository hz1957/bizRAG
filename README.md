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

- the official `OpenBMB/UltraRAG` source package (installed from GitHub, not the unrelated PyPI `ultrarag 1.0.0` package)
- `PyMySQL` for MySQL-backed metadata storage
- evaluation dependencies are optional and can be installed with `pip install -e ".[eval]"`

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
    sdk.py
    service/
    servers/
    pipelines/
    config/
```

Phase 5 deployment scaffolding is now included:

- `docker-compose.yml`
- `docker/Dockerfile`
- `docker/start_bizrag.sh`
- `.env.example`
- `bizrag/config/retriever_docker.yaml`

## Architecture Rules

Current project convention is `pipeline-first` for write paths.

- Standard write path: `service -> orchestrator -> sdk -> pipelines -> servers`
- Applies to: ingest, chunk, index, delete, rebuild, evaluation
- `service` should not directly orchestrate `servers` for multi-step write flows
- `retrieve/extract` are the current online read-path exception and may stay direct

If a new write capability is added, the expected order is:

1. add or reuse `bizrag/pipelines/*.yaml`
2. expose it via `bizrag/sdk.py` and `bizrag/service/orchestrator.py`
3. call it from `bizrag/service/*`

## SDK Usage

### SDK Helpers

```python
from bizrag.sdk import build_text_corpus, chunk_documents

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
python -m bizrag.entrypoints.retrieve_api \
  --retriever-config bizrag/servers/retriever/parameter.yaml \
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
- 项目结构与分层约束：[bizrag/docs/ProjectStructure.md](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/bizrag/docs/ProjectStructure.md:1)

## Phase 5 Deployment Template

The repository now includes a first-pass container deployment template for:

- `rustfs`
- `rabbitmq`
- `milvus`
- `mysql`
- `bizrag`

Use:

```bash
cp .env.example .env
docker compose up --build
```

Notes:

- `bizrag` currently runs API, MQ bridge, and worker in one container.
- `rustfs` is provided as a Phase 5 placeholder service behind the `rustfs` profile.
  Replace `RUSTFS_IMAGE` in `.env` with the actual image used in your environment, then start it with:

```bash
docker compose --profile rustfs up --build
```

- Metadata storage is expected to use MySQL in this deployment template.
- MySQL database and user are initialized by the standard `mysql` image environment variables in `.env`.
- BizRAG metadata tables are created automatically by `MetadataStore` on first startup; no separate SQL bootstrap is required for the current schema.
- `HF_CACHE_DIR` can be pointed at an existing HuggingFace cache directory to avoid downloading embedding models again inside the container.

### Docker Dev Hot Reload

The `bizrag` service is now configured for source-mounted development by default:

- `./bizrag -> /app/bizrag`
- `./docker -> /app/docker`
- `./pyproject.toml -> /app/pyproject.toml`

`BIZRAG_HOT_RELOAD` defaults to `true` in `docker-compose.yml`.
When enabled, the container runs a small supervisor that watches the mounted source tree
and automatically restarts:

- the retrieve API
- the RustFS worker
- the RustFS MQ bridge

This is intended for day-to-day service development, so changes under `bizrag/` or
`docker/` usually take effect without rebuilding the image.

Typical workflow:

```bash
docker compose up -d --build
docker compose logs -f bizrag
```

If you edit Python dependencies in `pyproject.toml`, you still need to rebuild the image:

```bash
docker compose up -d --build bizrag
```

To disable hot reload for a more production-like local run, set:

```bash
export BIZRAG_HOT_RELOAD=false
docker compose up -d bizrag
```

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

`--metadata-db` currently accepts either:

- a local SQLite file path, such as `bizrag/state/metadata.db`
- a MySQL DSN, such as `mysql+pymysql://user:password@127.0.0.1:3306/bizrag`

## Notes

- This is a source-style SDK integration, not a fully self-contained packaged SDK.
- If UltraRAG changes server signatures, the copied `server.yaml` files may need to
  be refreshed.
- `milvus_index` still requires a reachable Milvus instance and valid embedding
  backend configuration.
- In the current UltraRAG implementation, the copied `milvus_index` example is set
  to `is_demo: true` because that is the working path for Milvus indexing with
  document contents included.
