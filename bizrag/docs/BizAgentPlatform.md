# BizAgentPlatform 知识库接入方案

本文档是 `bizrag` 项目自己的平台接入方案文档，用于说明 BizAgent 智能体平台如何接入知识库、完成检索与后续 RAG 抽取，并约束本项目的分阶段落地范围。

目标如下：

- 支持 `md`、`txt`、`docx`、`doc`、`wps`、`pdf`、`xlsx/xls` 等文档接入
- 支持统一入库、切块、索引和检索
- 支持对外暴露标准化 `retrieve` 接口
- 支持后续接入 Rust 文档系统，并在文档更新时自动触发增量写入
- 为后续 `extract` 和 evaluation 提供统一数据基础

## 1. 当前项目能力边界

当前 `bizrag` 仓库已经具备以下基础能力：

- `corpus.build_text_corpus`：支持 `txt`、`md`、`docx`、`doc`、`wps`、`pdf`、`xps`、`oxps`、`epub`、`mobi`、`fb2`
- `corpus.mineru_parse + corpus.build_mineru_corpus`：适用于版面复杂 PDF
- `corpus.chunk_documents`：支持 `token`、`sentence`、`recursive` 三种 chunk 策略
- `biz_corpus.build_excel_corpus`：支持 Excel 按 sheet / 行转文本
- `retriever.retriever_init + retriever.retriever_index + retriever.retriever_search`：支持向量建索引与检索
- `bizrag.api`：承载 HTTP API 应用、路由、schema 和依赖装配
- `bizrag.entrypoints.api_http`：作为 HTTP 进程入口，负责加载配置并启动 API 应用
- `bizrag.entrypoints.kb_admin_cli`：对外暴露知识库注册、导入、删除、重建等管理命令
- `bizrag.service.ultrarag.pipeline_runner`：作为本地 UltraRAG pipeline 执行适配器
- `benchmark` / `evaluation`：支持基础离线评测
- `bizrag.infra.metadata_store`：当前已支持 `SQLite / MySQL` 双后端，默认仍可用本地 `metadata.db`
- `bizrag.contracts`：沉淀 API、worker、MQ bridge 共用的数据契约

当前仍然存在的限制：

- 知识库元数据已经有 SQLite 持久化层，但还没有独立服务化存储
- 已支持目录扫描、文档删除、集合重建，但当前索引更新仍以 KB 级重建为主
- 已落 `retrieve` 和最小规则式 `extract` API，但还没有接入生成式抽取模型
- 评测能力已接入项目，但还没有形成正式业务评测集

因此，当前项目不适合直接视为“已完成的平台服务”，更准确的状态是：Phase 1、Phase 2 已完成最小可用闭环，Phase 3 已落最小抽取与结构化评测能力，Phase 4 已完成最小接入版本，Phase 5 仍未开始。

### 1.1 当前仓库入口约定

本轮结构收敛后，当前项目统一采用以下入口：

- API 进程入口：`bizrag.entrypoints.api_http`
- Worker 进程入口：`bizrag.entrypoints.rustfs_worker_cli`
- MQ Bridge 进程入口：`bizrag.entrypoints.rustfs_mq_bridge_cli`
- HTTP 应用实现：`bizrag.api`
- 管理入口：`bizrag.entrypoints.kb_admin_cli`
- Pipeline 执行适配：`bizrag.service.ultrarag.pipeline_runner`
- API 容器启动时会在生命周期里触发读取链路 warmup（可通过 `BIZRAG_READ_WARMUP` 控制），因此“第一次请求”默认通常不再承受首次 MCP/模型初始化开销。
- 底层 server 根路径：`bizrag/servers/<name>`

不再使用旧的 `bizrag.src.*` 作为公开调用路径。

### 1.2 当前分层约束

当前项目采用 `pipeline-first` 约束，目的是避免平台层直接耦合底层处理算子。

- 写链路标准路径：`service/app -> service/ultrarag -> pipelines -> servers`
- 适用范围：知识库导入、chunk、索引、删除、重建、评测
- 约束原则：`service` 不直接编排 `servers`
- 在线读链路：`retrieve/extract` 也应通过 pipeline 执行，但入口仍在 `service`

这意味着：

- 平台接入层负责接请求、做鉴权、记任务、管状态
- `service/app` 负责平台语义，`service/ultrarag` 负责 UltraRAG 调用适配
- pipeline 层负责把多个原子能力拼成可复用流程
- server 层只负责单一能力本身，不承载平台业务流程

当前 `kb_admin` 已完成该约束收敛：导入、切块、增量索引、删除和重建均通过 pipeline 执行。

## 2. 推荐总体架构

推荐将知识库处理流程拆成 6 层：

1. 接入层：接收 BizAgentPlatform 上传文件、Rust 文档系统更新事件、批量目录导入
2. 预处理层：按文件类型做格式识别、去重、元数据补齐
3. Corpus 层：统一转成标准 `JSONL`
4. Chunk 层：切分为检索单元
5. Index 层：写入 Milvus
6. Retrieve 层：对外提供统一检索接口

建议目录结构如下：

```text
data/knowledge_base/
  raw/
    <kb_id>/
      <source files>
  corpus/
    <kb_id>.jsonl
  chunks/
    <kb_id>.jsonl
  index/
    <milvus metadata or local config>
```

对应知识库主流程：

```text
raw -> corpus -> chunks -> milvus_index -> retrieve
```

在当前工程实现中，建议进一步明确为：

```text
RustFS / Admin API
  -> service
  -> kb_pipeline
  -> pipelines
  -> servers
  -> Milvus / metadata
```

其中：

- `service` 负责平台语义
- `pipelines` 负责流程复用
- `servers` 负责底层原子能力

## 3. 统一数据模型

### 3.1 文本 Corpus 标准格式

统一使用 JSONL，每行一个文档对象：

```json
{
  "id": "contract_001",
  "title": "合同审批规范",
  "contents": "正文内容",
  "source_type": "pdf",
  "file_name": "合同审批规范.pdf",
  "kb_id": "bizagent_contract",
  "doc_version": "2026-04-15T10:00:00Z",
  "source_uri": "/data/contracts/合同审批规范.pdf"
}
```

建议保留字段：

- `id`：文档唯一 ID
- `title`：文档标题
- `contents`：正文内容
- `source_type`：来源类型，如 `md`、`pdf`、`docx`、`excel`
- `file_name`：原始文件名
- `kb_id`：知识库 ID
- `doc_version`：版本时间戳或内容 hash 对应版本号
- `source_uri`：原始来源地址
- `sheet_name` / `row_index`：Excel 专用字段

### 3.2 Chunk 标准格式

Chunk 后建议使用如下格式：

```json
{
  "id": 0,
  "doc_id": "contract_001",
  "title": "合同审批规范",
  "contents": "Title:\n合同审批规范\n\nContent:\n切分后的片段",
  "source_type": "pdf",
  "file_name": "合同审批规范.pdf",
  "kb_id": "bizagent_contract",
  "doc_version": "2026-04-15T10:00:00Z",
  "source_uri": "/data/contracts/合同审批规范.pdf"
}
```

这样在索引和召回阶段可以同时保留业务元数据与正文内容。

## 4. 文件类型处理策略

### 4.1 通用文本类

以下类型建议直接使用 `corpus.build_text_corpus`：

- `md`
- `txt`
- `docx`
- `doc`
- `wps`
- `pdf`

适用场景：

- 产品文档
- 操作手册
- 制度文档
- FAQ 文档

### 4.2 复杂 PDF

对于扫描版 PDF、表格较多的 PDF、图文混排 PDF，建议走：

```text
corpus.mineru_parse -> corpus.build_mineru_corpus
```

适用场景：

- 扫描版合同
- 复杂技术文档
- 带大量图表和公式的说明书

### 4.3 Excel / 表格类

Excel 建议走：

```text
biz_corpus.build_excel_corpus
```

处理建议：

- 逐个 sheet 读取
- 每一行转为结构化文本
- 对表头做标准化
- 对空行、合并单元格、备注列做清洗
- 每一行生成一条 corpus 记录，必要时按 3 到 10 行聚合成段

Linux 部署补充：

- `.doc/.wps` 建议预装 `libreoffice` 或 `soffice`
- 如果不装 LibreOffice，至少安装 `antiword` 或 `catdoc`
- `.xls` 依赖 `xlrd>=2.0.1`

推荐输出：

```json
{
  "id": "sales_2025#Sheet1#12",
  "title": "sales_2025 / Sheet1",
  "contents": "区域=华东；产品=A；销售额=120000；负责人=张三",
  "source_type": "excel",
  "file_name": "sales_2025.xlsx",
  "sheet_name": "Sheet1",
  "row_index": 12,
  "kb_id": "sales_kb"
}
```

## 5. 推荐 Pipeline 设计

本节不仅描述 pipeline 示例，也作为项目内写链路实现规范：

- 新增写链路功能时，优先补 pipeline，而不是在 `service` 中直接 import `servers`
- `service` 侧只应调用 `kb_pipeline` 或 `pipeline_runner`，不应散落底层 server 细节

### 5.1 文本类入库 Pipeline

适用于 `md/doc/docx/pdf/txt`：

```yaml
servers:
  corpus: bizrag/servers/corpus

pipeline:
- corpus.build_text_corpus
```

### 5.2 复杂 PDF 入库 Pipeline

```yaml
servers:
  corpus: bizrag/servers/corpus

pipeline:
- corpus.mineru_parse
- corpus.build_mineru_corpus
```

### 5.3 Excel 入库 Pipeline

```yaml
servers:
  biz_corpus: bizrag/servers/biz_corpus

pipeline:
- biz_corpus.build_excel_corpus
```

### 5.4 Chunk Pipeline

```yaml
servers:
  corpus: bizrag/servers/corpus

pipeline:
- corpus.chunk_documents
```

推荐参数：

```yaml
corpus:
  raw_chunk_path: data/knowledge_base/corpus/bizagent_contract.jsonl
  chunk_path: data/knowledge_base/chunks/bizagent_contract.jsonl
  chunk_backend: sentence
  tokenizer_or_token_counter: character
  chunk_size: 512
  use_title: true
  chunk_backend_configs:
    sentence:
      chunk_overlap: 50
      min_sentences_per_chunk: 1
      delim: "['.', '!', '?', '；', '。', '！', '？', '\\n']"
```

经验建议：

- 中文业务文档优先使用 `sentence`
- 规章制度、FAQ、公告类文档可使用 `chunk_size=384~768`
- Excel 转文本后的记录通常不需要复杂 chunk，可直接轻切或跳过 chunk

### 5.5 索引 Pipeline

推荐统一写入 `Milvus`：

```yaml
servers:
  retriever: bizrag/servers/retriever

pipeline:
- retriever.retriever_init
- retriever.retriever_index
```

推荐原因：

- 支持多知识库
- 支持追加写入
- 支持按 `collection_name` 管理
- 更适合平台化服务

## 6. BizAgentPlatform 编排建议

平台侧不建议直接把底层 pipeline 暴露给上层业务，而是应增加一层编排服务。

建议流程：

```text
文件上传 / Rust 更新事件
  -> 文件识别
  -> 去重与版本判断
  -> 选择解析 pipeline
  -> 输出 corpus.jsonl
  -> chunk
  -> index to milvus
  -> 更新 kb metadata
```

建议平台内部定义如下任务类型：

- `ingest_text`
- `ingest_pdf_complex`
- `ingest_excel`
- `chunk_corpus`
- `index_chunks`
- `delete_document`
- `rebuild_collection`

## 7. Retrieve 接口设计

### 7.1 对外业务接口

当前项目以如下接口作为 Phase 1 标准：

```text
POST /api/v1/retrieve
```

请求：

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

返回：

```json
{
  "items": [
    {
      "content": "检索到的文本片段",
      "score": 0.83,
      "doc_id": "contract_001",
      "title": "合同审批规范",
      "file_name": "合同审批规范.pdf",
      "source_type": "pdf",
      "sheet_name": null,
      "row_index": null,
      "kb_id": "bizagent_contract",
      "doc_version": "2026-04-15T10:00:00Z"
    }
  ]
}
```

平台内部逻辑：

```text
kb_id -> KB metadata/runtime state
query -> structured retriever
filters -> milvus filter
ret_items -> 业务结构化包装
```

当前启动示例：

```bash
python -m bizrag.entrypoints.api_http \
  --metadata-db bizrag/state/metadata.db
```

当前服务还同时暴露：

- `POST /api/v1/extract`
- `POST /api/v1/admin/kbs/register`
- `POST /api/v1/admin/kbs/ingest`
- `POST /api/v1/admin/kbs/delete-document`
- `POST /api/v1/admin/kbs/rebuild`
- `GET /api/v1/admin/kbs`
- `GET /api/v1/admin/kbs/{kb_id}/documents`
- `GET /api/v1/admin/tasks`
- `GET /api/v1/admin/events`
- `POST /api/v1/admin/tasks/{task_id}/retry`
- `POST /api/v1/admin/events/{event_id}/replay`
- `POST /api/v1/events/rustfs`
- `POST /api/v1/events/rustfs/batch`
- `POST /api/v1/events/rustfs/queue`
- `POST /api/v1/events/rustfs/queue/batch`

### 7.2 后续建议增强

为了支持引用和溯源，返回字段建议长期保留：

- `content`
- `score`
- `doc_id`
- `title`
- `file_name`
- `source_type`
- `sheet_name`
- `row_index`
- `kb_id`
- `doc_version`
- `source_uri`

## 7.3 Extract 接口设计

当前项目已增加如下接口：

```text
POST /api/v1/extract
```

请求：

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

返回：

```json
{
  "result": {
    "total_price": 3286723.0
  },
  "field_results": [
    {
      "name": "total_price",
      "value": 3286723.0,
      "status": "filled",
      "confidence": 0.75,
      "reason": "key_value,alias:共计",
      "evidence": [
        {
          "doc_id": "contract_001",
          "file_name": "合同审批规范.pdf",
          "source_uri": "/data/contracts/合同审批规范.pdf"
        }
      ]
    }
  ],
  "citations": [],
  "status": "success",
  "missing_required_fields": []
}
```

当前实现说明：

- 当前抽取基于召回证据做规则匹配，不依赖外部 LLM
- 支持 `string/number/integer/boolean/enum`
- 支持 `aliases/patterns/enum_values/normalizers`
- 每个字段返回证据片段，便于后续做引用和评测

结构化评测数据建议格式：

```json
{
  "question": "康龙化成 NMPA的IND项目报价总价是多少",
  "pred_output": {
    "total_price": 3286723.0
  },
  "expected_output": {
    "total_price": "3286723"
  },
  "pred_citations": {
    "total_price": ["7c2a5ee28f7aea25::报价单_TSP--2024-4-23（NMPA，口服IND package）"]
  },
  "expected_citations": {
    "total_price": ["7c2a5ee28f7aea25::报价单_TSP--2024-4-23（NMPA，口服IND package）"]
  }
}
```

## 8. Rust 文档系统接入方案

如果后续 BizAgentPlatform 需要接入 Rust 文档系统，建议采用事件驱动增量入库。

### 8.1 目标

当 Rust 文档系统中的文档发生以下变化时，自动触发知识库更新：

- 新增文档
- 文档内容修改
- 文档删除
- 文档重命名

### 8.2 推荐集成方式

推荐两种方式：

1. Webhook 事件推送
2. 周期扫描 + 内容 hash 比对

优先使用 Webhook。

当前项目已提供最小事件接入端点：

```text
POST /api/v1/events/rustfs
POST /api/v1/events/rustfs/batch
POST /api/v1/events/rustfs/queue
POST /api/v1/events/rustfs/queue/batch
```

当前实现约束：

- 事件可以通过以下任一种方式携带内容：
  - 本地可访问路径：`payload_path`
  - 远程下载地址：`download_url`
  - 内联文本：`payload_text`
  - Base64 内容：`payload_base64`
- `document.created` / `document.updated` 会映射为 `ingest-path`
- `document.deleted` 会映射为 `delete-document`
- `document.renamed` 会执行“删除旧路径 + 导入新路径”
- 如果使用远程 URL 或内联内容，BizRAG 会先物化为临时文件，再按稳定的 `source_uri` 入库
- 为了保证后续删除和重命名能定位到原文档，事件中仍建议稳定提供 `source_uri` / `old_source_uri` / `new_source_uri`
- 支持通过 `X-Rustfs-Token` 做共享令牌校验
- 支持通过 `X-Rustfs-Timestamp` + `X-Rustfs-Signature` 做 HMAC-SHA256 签名校验
- 所有 RustFS 事件会落到 `rustfs_events` 表，支持查询与重放
- 批量事件端点可作为消息队列消费者的落地入口，由上游消费者聚合后转发到 BizRAG
- 当前项目已新增独立 worker：`python -m bizrag.entrypoints.rustfs_worker_cli`
- 推荐接法是“事件先入队，再由 worker 异步消费”，避免 webhook 长时间阻塞
- 当前项目已新增 MQ bridge：`python -m bizrag.entrypoints.rustfs_mq_bridge_cli`
- Kafka / RabbitMQ 推荐作为上游事件总线，bridge 负责把外部消息转存到 SQLite 队列

当前推荐部署链路：

```text
RustFS -> Kafka / RabbitMQ -> rustfs_mq_bridge -> SQLite rustfs_events -> rustfs_worker -> BizRAG ingest/delete/index
```

启动示例：

```bash
pip install .[mq]
python -m bizrag.entrypoints.rustfs_mq_bridge_cli \
  --backend kafka \
  --bootstrap-servers localhost:9092 \
  --topic bizrag.rustfs.events
```

```bash
python -m bizrag.entrypoints.rustfs_mq_bridge_cli \
  --backend rabbitmq \
  --amqp-url amqp://guest:guest@127.0.0.1/ \
  --queue bizrag.rustfs.events
```

```bash
python -m bizrag.entrypoints.rustfs_worker_cli \
  --metadata-db bizrag/state/metadata.db \
  --poll-interval 2 \
  --batch-size 10
```

联调脚本：

```bash
./scripts/rabbitmq_e2e.sh
```

CI smoke test：

```bash
./scripts/ci_smoke_rabbitmq.sh
```

推荐事件示例：

```json
{
  "event_type": "document.updated",
  "kb_id": "rust_docs",
  "source_uri": "rustfs://service/order_api_001",
  "file_name": "order_api.md",
  "content_type": "text/markdown",
  "download_url": "https://rustfs.internal/api/v1/files/order_api_001/content"
}
```

或：

```json
{
  "event_type": "document.created",
  "kb_id": "rust_docs",
  "source_uri": "rustfs://service/faq_001",
  "file_name": "faq_001.md",
  "payload_text": "# FAQ\\n\\n这里是文档正文"
}
```

### 8.3 事件模型

Rust 文档系统建议向 BizAgentPlatform 推送如下事件：

```json
{
  "event_type": "document.updated",
  "kb_id": "rust_docs",
  "doc_id": "order_api_001",
  "source_uri": "rustdoc://service/order_api_001",
  "file_name": "order_api.md",
  "content_type": "md",
  "version": "2026-04-15T10:30:00Z",
  "content_hash": "sha256:xxxx",
  "payload_path": "/data/rust_docs/order_api.md"
}
```

建议事件类型：

- `document.created`
- `document.updated`
- `document.deleted`
- `document.renamed`

## 9. 分阶段落地计划

### Phase 1：召回服务最小闭环

目标：把当前工程从“能力碎片”变成“可被 BizAgent 平台调用的召回服务”。

包括：

- 修正 pipeline / server 路径与服务入口
- 打通文本、Excel、chunk、index、retrieve 调用链
- 实现 `POST /api/v1/retrieve`
- 支持结构化返回：`content/score/doc_id/title/file_name/source_type/sheet_name/row_index/kb_id`
- 支持基础 filter：`kb_id/source_type/file_name/doc_id`
- 引入 `benchmark` / `evaluation` server 与最小评测 pipeline
- 补充项目内文档和启动说明

当前状态：

- 已完成
- 已完成真实代码落地、包结构收敛和 CLI 入口统一
- 已具备最小联调和离线评测闭环

### Phase 2：知识库接入与索引编排

目标：从“可检索”提升到“可持续维护知识库”。

包括：

- 建设 ingest 编排层
- 建设知识库元数据存储
- 支持 `content_hash/doc_version` 管理
- 支持增量更新、文档删除、集合重建
- 建设导入任务状态机与失败重试机制

交付结果：

- 支持持续写入
- 支持增量同步
- 支持删除与重建

当前实现：

- 已新增 `bizrag.entrypoints.kb_admin_cli`
- 已新增可切换的元数据存储层：默认可使用 SQLite `bizrag/state/metadata.db`，Phase 5 可切到 MySQL DSN
- 已支持 `register-kb`、`ingest-path`、`delete-document`、`rebuild-kb`、`retry-task`
- 已支持目录扫描、内容 hash 去重、文档级 corpus/chunk 产物、集合级重建

当前命令示例：

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

```bash
python -m bizrag.entrypoints.kb_admin_cli \
  delete-document \
  --kb-id bizrag_bcrp \
  --source-uri raw_knowledge/真实案例/案例1/1、MTD&DRF study in Rat-NTSL.xlsx
```

当前边界：

- 文档变化已经支持“检测和重建”，但索引更新仍采用 KB 级重建，而不是 Milvus 内的细粒度局部 upsert/delete
- `prefer-mineru` 仅在本地存在 `mineru` 可执行程序时可用
- 任务状态已持久化，但自动重试策略当前仍由 `retry-task` 显式触发

### Phase 3：抽取能力与业务评测

目标：从“召回服务”扩展成“knowledgebase + RAG extraction service”。

包括：

- 实现 `POST /api/v1/extract`
- 引入结构化字段 schema
- 返回抽取结果及引用证据
- 建立检索 + 抽取联合评测
- 建立字段级 `EM/F1/JSON 合法率/引用命中率`

交付结果：

- 平台可直接调用抽取接口
- 可以量化抽取质量
- 能区分检索错误与抽取错误

当前实现：

- 已新增 `POST /api/v1/extract`
- 已新增规则式结构化抽取引擎
- 已支持字段级 `EM/F1/ACC/record_em/schema_valid/citation_hit_rate`
- 已新增 `bizrag/pipelines/evaluate_structured_results.yaml`

当前边界：

- 当前抽取还不是生成式 schema filling，而是基于证据片段的规则抽取
- 更复杂的跨段推理、表格聚合和单位换算仍需要后续引入 LLM 或专门解析器

### Phase 4：平台接入与服务化

目标：把当前能力从“可本地运行”推进到“可被上游文档系统和平台标准化接入”。

包括：

- 增加知识库管理型 HTTP API，替代纯 CLI 方式接入
- 增加 RustFS 文档系统接入适配层
- 支持 `document.created/updated/deleted/renamed` 事件驱动导入
- 建设 webhook / 事件消费能力
- 建设平台侧任务编排与状态回传能力
- 从 KB 级重建逐步演进到文档级增量更新

交付结果：

- BizRAG 可作为平台标准知识库服务能力被外部系统调用
- RustFS 等文档系统可以通过统一协议接入
- 文档系统更新可以自动驱动知识库同步

当前状态：

- 已完成可联调版本
- 已新增管理型 HTTP API
- 已新增 RustFS 事件接入端点
- 已新增 RustFS 事件批量接入、事件查询和事件重放接口
- 已新增 RustFS 事件入队接口和独立异步消费 worker
- 已新增 Kafka / RabbitMQ 适配桥接进程
- 当前 RustFS 接入已支持本地路径、远程下载地址和内联内容三种接法
- 已支持共享 token 和 HMAC 签名校验
- 已支持失败事件留痕和显式重放
- 已支持基于 SQLite 持久化队列的事件消费
- 已支持 `Kafka/RabbitMQ -> SQLite queue -> worker` 的两段式消费架构
- 已支持单文档导入、RustFS 更新和单文档删除的局部索引更新
- 已支持目录级批量同步的批量增量更新
- 当前仅在批量增量更新失败时回退到 KB 级重建

Phase 4 当前归属：

- 属于 Phase 4：
  - RustFS webhook 接入
  - 事件认证与签名校验
  - 事件落库、查询、失败补偿和重放
  - 事件入队和独立 worker 消费
  - Kafka / RabbitMQ 适配层
  - 批量事件接入和队列友好型消费入口
  - 单文档局部索引更新
- 属于 Phase 5：
  - 多租户隔离
  - 平台级权限控制
  - 监控、告警、审计、限流、发布回滚等生产治理

### Phase 5：生产化与运维能力

目标：把服务推进到平台正式接入所需的稳定度。

包括：

- 可观测性与运行诊断
  - 补统一日志、trace、metrics
  - 补健康检查、核心指标看板、告警规则
  - 覆盖 ingest、queue、worker、index、retrieve、extract 等关键链路
- 稳定性与流量治理
  - 补超时、重试、限流、熔断、幂等控制
  - 补队列积压监控、死信策略、失败补偿
  - 增加容量评估与成本治理
- 安全与租户隔离
  - 做多租户隔离
  - 做平台级权限控制
  - 增加密钥与配置管理
  - 增加审计日志
- 交付与发布治理
  - 补 Docker 镜像与部署模板
  - 明确标准容器化部署形态：`rustfs`、`rabbitmq`、`milvus`、`mysql`、`bizrag`
  - 提供 `docker-compose` 级部署模板，明确容器职责、网络关系、挂载目录和健康检查
  - `bizrag` 在当前阶段可先保持单容器部署；当读写压力、扩容和故障隔离要求上来后，再拆分为 `bizrag-api` 和 `bizrag-worker`
  - 建立 CI/CD、smoke test、回归门禁
  - 建立灰度、回滚、版本兼容策略
- 数据可靠性
  - 补 mysql/Milvus 数据备份恢复
  - 增加索引一致性检查
  - 输出灾难恢复与运维 runbook

交付结果：

- 服务可稳定运行
- 出问题可定位、可回滚
- 数据可恢复、可审计
- 具备正式接入条件
- 形成统一的标准部署拓扑，便于测试、预发和生产环境复用

当前仓库已补第一版部署模板：

- [docker-compose.yml](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/docker-compose.yml:1)
- [docker/Dockerfile](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/docker/Dockerfile:1)
- [docker/start_bizrag.sh](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/docker/start_bizrag.sh:1)
- [bizrag/servers/retriever/parameter.docker.yaml](/Users/haoming.zhang/PyCharmMiscProject/bizRAG/bizrag/servers/retriever/parameter.docker.yaml:1)

说明：

- 当前模板默认 `bizrag` 单容器运行 `retrieve_api + rustfs_mq_bridge + rustfs_worker`
- `mysql` 作为 metadata 控制面存储
- MySQL 库和账号由容器环境变量初始化，BizRAG 自己会在首次启动时自动建 metadata 表
- `milvus` 作为独立向量检索组件
- `rustfs` 服务在模板中以占位方式提供，需按实际环境替换 `RUSTFS_IMAGE`；默认放在 `rustfs` profile 下，不会在基础 compose 启动时自动拉起

Phase 5 可观测性当前已落地的接口：

- `GET /api/v1/admin/ops/health`
  - 返回统一健康检查，覆盖 `metadata_store`、`read_service`、`rustfs_queue`
  - 并汇总最近窗口内 `ingest`、`queue`、`worker`、`index`、`retrieve`、`extract` 的组件状态
- `GET /api/v1/admin/ops/overview`
  - 返回 inventory、component latency、active alerts、recent spans
- `GET /api/v1/admin/ops/spans`
  - 返回持久化 operation spans，可按 `component`、`kb_id`、`trace_id`、`status` 过滤
- `GET /api/v1/admin/ops/metrics`
  - 返回 Prometheus 风格 metrics
- `GET /ops`
  - 返回基于 overview API 的轻量级 web dashboard

说明：

- operation span 会落到 metadata store，因此 API、MQ bridge、worker 是跨进程统一可见的
- 当前告警规则覆盖：
  - 队列积压
  - worker stalled
  - retrieve/extract 高延迟
  - 最近窗口失败操作
