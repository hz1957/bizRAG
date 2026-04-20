# bizRAG

`bizRAG` is a minimal integration project that uses the `ultrarag` Python package
while keeping the local pipeline and server assets that UltraRAG expects:

- `servers/`
- `examples/*.yaml`
- `examples/parameter/*.yaml`
- `examples/server/*_server.yaml`

This layout matches the current UltraRAG pipeline behavior:

- `PipelineCall(...)` needs local pipeline YAML and parameter YAML files
- `ToolCall.initialize(...)` needs a local `server_root`
- `ToolCall` also expects `servers/<name>/server.yaml`

## Install

```bash
pip install -e .
```

Editable install is recommended because the current integration reads local
`servers/` and `pipelines/` files from the repository.

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
- `bizrag/servers/retriever/parameter.docker.yaml`

## Architecture Rules

Current project convention is `pipeline-first`.

- Standard write path: `endpoint -> service/app -> pipelines -> servers`
- Applies to: ingest, chunk, index, delete, rebuild, evaluation
- `service` should not directly orchestrate `servers` for multi-step write flows
- `retrieve/extract` now follow `endpoint -> service -> pipelines -> servers`

If a new write capability is added, the expected order is:

1. add or reuse `bizrag/pipelines/*.yaml`
2. call it from `bizrag/service/app/*` with `bizrag/service/ultrarag/pipeline_runner.py`
3. keep UltraRAG-specific adaptation inside `servers/*` or pipeline companion yaml when possible

## Pipeline Runner

Internal pipeline execution is handled by `bizrag/service/ultrarag/pipeline_runner.py`.

```python
from bizrag.service.ultrarag.pipeline_runner import DEFAULT_PIPELINE_RUNNER

await DEFAULT_PIPELINE_RUNNER.run(
    "build_text_corpus",
    params={
        "corpus": {
            "parse_file_path": "data/raw",
            "text_corpus_save_path": "data/corpus/text.jsonl",
        }
    },
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

Phase 1 adds a BizAgent-facing HTTP API:

```bash
python -m bizrag.entrypoints.api_http \
  --metadata-db bizrag/state/metadata.db
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

## Observability

Phase 5 now includes a first-pass observability surface for the core chains:

- `ingest`
- `queue`
- `worker`
- `index`
- `retrieve`
- `extract`

Available endpoints:

- `GET /api/v1/admin/ops/health`
- `GET /api/v1/admin/ops/overview`
- `GET /api/v1/admin/ops/spans`
- `GET /api/v1/admin/ops/metrics`
- `GET /ops`

`/ops` is a lightweight web UI backed by the overview API and auto-refreshes in the browser.
`/api/v1/admin/ops/metrics` returns Prometheus-style text metrics.
Operation spans are persisted through `MetadataStore`, so API, MQ bridge, and worker activity
can be inspected in one place instead of only in process-local logs.

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
- Container compute mode is controlled by:
  - `BIZRAG_ACCELERATOR=cpu|cuda|auto`
  - `BIZRAG_GPU_IDS` when `BIZRAG_ACCELERATOR=cuda`
- The default compose template uses `BIZRAG_ACCELERATOR=cpu`, which is the correct mode for Docker on macOS.
- Read path warmup is controlled by:
  - `BIZRAG_READ_WARMUP=true|false`
  - `BIZRAG_READ_WARMUP_MODE=all|first|none`
  - `BIZRAG_READ_WARMUP_KB_IDS=kb_a,kb_b`
- The default compose template enables startup warmup so the first retrieval requests are already prepared after container boot.
- `BIZRAG_READ_WARMUP` controls whether warmup runs at startup (default: true).
- warmup mode is controlled by `BIZRAG_READ_WARMUP_MODE=all|first|none` and affects how many KBs are actively probed during startup.
- `rustfs` is provided as a Phase 5 placeholder service behind the `rustfs` profile.
  Replace `RUSTFS_IMAGE` in `.env` with the actual image used in your environment, then start it with:

```bash
docker compose --profile rustfs up --build
```

- Metadata storage is expected to use MySQL in this deployment template.
- MySQL database and user are initialized by the standard `mysql` image environment variables in `.env`.
- BizRAG metadata tables are created automatically by `MetadataStore` on first startup; no separate SQL bootstrap is required for the current schema.
- `HF_CACHE_DIR` can be pointed at an existing HuggingFace cache directory to avoid downloading embedding models again inside the container.
- `BIZRAG_HF_OFFLINE` defaults to `true` in the container profile so retriever/reranker startup uses the mounted local cache instead of probing HuggingFace over the network.

### Docker Hot Reload

The `bizrag` service mounts source into the container:

- `./bizrag -> /app/bizrag`
- `./docker -> /app/docker`
- `./pyproject.toml -> /app/pyproject.toml`

`BIZRAG_HOT_RELOAD` defaults to `false` in `docker-compose.yml`.
When enabled, the container runs a small supervisor that watches the mounted source tree
and automatically restarts:

- the retrieve API
- the RustFS worker
- the RustFS MQ bridge

Keep it disabled for normal container runs so startup warmup happens once at container
boot instead of being interrupted by source watching. Enable it only for day-to-day
service development, where changes under `bizrag/` or `docker/` should take effect
without rebuilding the image.

Typical workflow:

```bash
docker compose up -d --build
docker compose logs -f bizrag
```

If you want dev hot reload:

```bash
export BIZRAG_HOT_RELOAD=true
docker compose up -d bizrag
```

If you edit Python dependencies in `pyproject.toml`, you still need to rebuild the image:

```bash
docker compose up -d --build bizrag
```

To return to the default container mode:

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
python -m bizrag.entrypoints.kb_admin_cli \
  register-kb \
  --kb-id bizrag_bcrp \
  --retriever-config bizrag/servers/retriever/parameter.local.yaml \
  --source-root raw_knowledge/真实案例
```

```bash
python -m bizrag.entrypoints.kb_admin_cli \
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
