# BizAgentPlatform 知识库接入方案

本文档给出 BizAgentPlatform 平台的知识库建设方案，目标是基于 UltraRAG 搭建一套可持续写入、可增量更新、可统一检索暴露的企业知识库基础设施。

设计目标如下：

- 支持 `md`、`txt`、`docx`、`doc`、`wps`、`pdf`、`xlsx/xls` 等文档接入
- 支持统一入库、切块、索引和检索
- 支持对外暴露标准化 `retrieve` 接口
- 支持后续接入 Rust 文档系统，并在文档更新时自动触发增量写入
- 与 UltraRAG 现有的 Server / Pipeline / UI 知识库管理能力保持一致

## 1. 现有能力边界

结合当前仓库实现，UltraRAG 已具备以下基础能力：

- `corpus.build_text_corpus`：支持 `txt`、`md`、`docx`、`doc`、`wps`、`pdf`、`xps`、`oxps`、`epub`、`mobi`、`fb2`
- `corpus.mineru_parse + corpus.build_mineru_corpus`：适用于版面复杂 PDF
- `corpus.chunk_documents`：支持 `token`、`sentence`、`recursive` 三种 chunk 策略
- `retriever.retriever_init + retriever.retriever_index + retriever.retriever_search`：支持向量建索引与检索
- `script/deploy_retriever_server.py`：已经提供了一个 HTTP 检索服务包装

当前实现中的重要限制：

- `build_text_corpus` 目前不支持 `excel/xls/xlsx`
- 默认的 HTTP 检索接口只返回 `ret_psg` 文本列表，不直接返回 score、metadata
- 如果走 UI 当前的知识库链路，索引阶段默认更适合 `Milvus`

因此，BizAgentPlatform 不建议做成“单条 pipeline 吞掉所有格式”，而是建议采用分层架构。

## 2. 推荐总体架构

推荐将知识库处理流程分成 6 层：

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

这与当前 UI 中的知识库分层保持一致：

```text
raw -> corpus -> chunks -> milvus_index
```

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
  "doc_version": "2026-04-15T10:00:00Z"
}
```

建议保留以下字段：

- `id`：文档唯一 ID
- `title`：文档标题
- `contents`：正文内容
- `source_type`：来源类型，如 `md`、`pdf`、`docx`、`excel`
- `file_name`：原始文件名
- `kb_id`：知识库 ID
- `doc_version`：版本时间戳或内容 hash 对应的版本号
- `source_uri`：可选，原始来源地址
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
  "doc_version": "2026-04-15T10:00:00Z"
}
```

这样后续写入 Milvus 时，除 `contents` 外还能保留业务元数据。

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

Excel 目前不是 `build_text_corpus` 的原生支持格式，因此建议新增一个自定义 Server，例如：

```text
servers/biz_corpus
```

并提供：

```text
biz_corpus.build_excel_corpus
```

处理建议：

- 逐个 sheet 读取
- 每一行转为结构化文本
- 对表头做标准化
- 对空行、合并单元格、备注列做清洗
- 每一行生成一条 corpus 记录，必要时按 3 到 10 行聚合成段

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

这样做比“先把整张表拼成长文，再做通用 chunk”更适合业务检索。

## 5. 推荐 Pipeline 设计

### 5.1 文本类入库 Pipeline

适用于 `md/doc/docx/pdf/txt`：

```yaml
servers:
  corpus: servers/corpus

pipeline:
- corpus.build_text_corpus
```

参数示例：

```yaml
corpus:
  parse_file_path: data/knowledge_base/raw/bizagent_contract/
  text_corpus_save_path: data/knowledge_base/corpus/bizagent_contract.jsonl
```

### 5.2 复杂 PDF 入库 Pipeline

```yaml
servers:
  corpus: servers/corpus

pipeline:
- corpus.mineru_parse
- corpus.build_mineru_corpus
```

参数示例：

```yaml
corpus:
  parse_file_path: data/knowledge_base/raw/bizagent_manual/
  mineru_dir: data/knowledge_base/mineru/bizagent_manual/
  text_corpus_save_path: data/knowledge_base/corpus/bizagent_manual.jsonl
  image_corpus_save_path: data/knowledge_base/corpus/bizagent_manual_images.jsonl
```

### 5.3 Excel 入库 Pipeline

建议新增：

```yaml
servers:
  biz_corpus: servers/biz_corpus

pipeline:
- biz_corpus.build_excel_corpus
```

参数示例：

```yaml
biz_corpus:
  parse_file_path: data/knowledge_base/raw/sales_kb/
  text_corpus_save_path: data/knowledge_base/corpus/sales_kb.jsonl
  sheet_mode: row
  include_header: true
```

### 5.4 Chunk Pipeline

```yaml
servers:
  corpus: servers/corpus

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
- 表格转文本后的 Excel 记录通常不需要再做复杂 chunk，可直接轻切或跳过 chunk

### 5.5 索引 Pipeline

BizAgentPlatform 推荐统一写入 `Milvus`，而不是 `FAISS`。

原因如下：

- 支持多知识库
- 支持追加写入
- 支持按 `collection_name` 管理
- 更适合平台化服务

Pipeline：

```yaml
servers:
  retriever: servers/retriever

pipeline:
- retriever.retriever_init
- retriever.retriever_index
```

参数示例：

```yaml
retriever:
  is_demo: true
  corpus_path: data/knowledge_base/chunks/bizagent_contract.jsonl
  collection_name: bizagent_contract
  batch_size: 32
  backend_configs:
    openai:
      model_name: text-embedding-3-small
      base_url: https://api.openai.com/v1
      api_key: ${EMBED_API_KEY}
      concurrency: 8
  index_backend_configs:
    milvus:
      uri: http://milvus:19530
      token: null
      id_field_name: id
      vector_field_name: vector
      text_field_name: contents
      metric_type: IP
      index_params:
        index_type: AUTOINDEX
        metric_type: IP
      search_params:
        metric_type: IP
        params: {}
```

说明：

- 当前 UI 的知识库执行路径更偏向 `is_demo=true + openai embedding + milvus`
- 如果后续要切到私有 embedding 模型，建议补一套“非 demo 模式的 Milvus 索引配置”

## 6. BizAgentPlatform 的统一处理编排

平台侧建议不要直接暴露 UltraRAG 的底层 pipeline 给上层业务，而是增加一层 BizAgentPlatform 编排服务。

建议流程如下：

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

这样可以让调度系统更清晰，失败重试也更简单。

## 7. Retrieve 接口设计

### 7.1 当前可直接复用的接口

当前仓库已提供 HTTP 检索服务：

```text
POST /search
```

请求：

```json
{
  "query_list": ["怎么申请合同审批"],
  "top_k": 5,
  "query_instruction": "",
  "collection_name": "bizagent_contract"
}
```

返回：

```json
{
  "ret_psg": [
    ["chunk1", "chunk2", "chunk3"]
  ]
}
```

### 7.2 BizAgentPlatform 对外接口建议

BizAgentPlatform 建议封装一个更稳定的业务接口：

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

返回建议：

```json
{
  "items": [
    {
      "content": "检索到的文本片段",
      "doc_id": "contract_001",
      "title": "合同审批规范",
      "file_name": "合同审批规范.pdf",
      "source_type": "pdf",
      "sheet_name": null
    }
  ]
}
```

平台内部逻辑：

```text
kb_id -> collection_name
query -> UltraRAG /search
ret_psg -> 业务结构化包装
```

### 7.3 建议做的增强

如果后续要在 BizAgentPlatform 中展示引用来源，建议把检索返回从“纯文本列表”升级为：

- `content`
- `score`
- `doc_id`
- `title`
- `file_name`
- `source_type`
- `sheet_name`
- `row_index`

这样更适合 Agent 在回答时做引用和溯源。

## 8. Rust 文档系统接入方案

如果后续 BizAgentPlatform 需要接入 Rust 文档系统，建议采用“事件驱动增量入库”。

### 8.1 目标

当 Rust 文档系统中的文档发生以下变化时，自动触发知识库更新：

- 新增文档
- 文档内容修改
- 文档删除
- 文档重命名

### 8.2 推荐集成方式

推荐两种方式，优先级如下：

1. Webhook 事件推送
2. 周期扫描 + 内容 hash 比对

推荐优先使用 Webhook，因为它更实时，也更容易做增量。

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

### 8.4 更新触发链路

推荐链路如下：

```text
Rust 文档系统
  -> webhook / event bus
  -> BizAgentPlatform ingestion worker
  -> 检查 doc_id + content_hash
  -> 若内容变化则重新生成 corpus
  -> 删除旧 chunk / 旧索引记录
  -> 写入新 chunk / 新索引
  -> 更新 metadata 状态
```

### 8.5 去重与幂等

必须做的控制项：

- 以 `doc_id + content_hash` 作为幂等键
- 如果 `content_hash` 不变，则跳过重复写入
- 如果 `doc_id` 存在但 hash 变化，则执行增量重建
- 如果收到 `document.deleted`，则删除该文档对应的 chunk 和索引

### 8.6 删除与重建策略

建议 Milvus 层支持两种策略：

1. 文档级删除
2. 知识库级重建

文档级删除适用于：

- 单篇文档更新
- 单篇文档删除

知识库级重建适用于：

- 大版本文档更新
- 文档结构大规模变更
- chunk 策略变更
- embedding 模型切换

### 8.7 Rust 文档的特殊建议

如果 Rust 文档系统输出的是结构化文档树，建议保留以下元数据：

- `module_path`
- `section_path`
- `anchor`
- `language`
- `service_name`
- `owner_team`

这样 BizAgentPlatform 在检索后可以直接跳转回原始文档节点。

## 9. 推荐增量入库实现

建议在 BizAgentPlatform 增加一个增量入库 Worker：

```text
IngestionWorker
  - receive_event()
  - detect_format()
  - compute_hash()
  - choose_pipeline()
  - build_corpus()
  - chunk()
  - index()
  - update_status()
```

### 9.1 处理策略

- `md/txt/docx/doc/wps/pdf`：直接进入文本 pipeline
- 复杂 PDF：进入 MinerU pipeline
- `xlsx/xls`：进入 Excel pipeline
- Rust 文档事件：按 `doc_id` 单文档增量处理

### 9.2 建议状态机

每个文档建议维护状态：

- `pending`
- `parsing`
- `chunking`
- `indexing`
- `ready`
- `failed`
- `deleted`

这样便于平台观察入库进度和失败定位。

## 10. 配置建议

### 10.1 初期推荐

适合先快速落地：

- Chunk：`sentence`
- Chunk size：`512`
- Overlap：`50`
- Index：`Milvus`
- Embedding：先用 OpenAI 兼容接口，后续再切私有模型

### 10.2 中期优化

等平台跑稳后再做：

- 为 Excel 单独优化 chunk 策略
- 检索返回补充 metadata 与 score
- 支持文档级删除和文档级重建
- 引入 rerank
- 支持租户级隔离

### 10.3 长期演进

- 引入混合检索：向量检索 + BM25
- 引入多模态检索：图片页、扫描件
- 引入版本化知识库
- 引入基于事件总线的实时知识更新

## 11. 推荐实施顺序

建议分三阶段实施：

### Phase 1：最小可用版本

- 打通 `md/doc/docx/pdf` 入库
- 打通 `chunk -> milvus -> retrieve`
- BizAgentPlatform 暴露统一 `/retrieve`

### Phase 2：增强接入能力

- 新增 `build_excel_corpus`
- 新增复杂 PDF 的 MinerU 链路
- 检索结果补充 metadata

### Phase 3：事件驱动知识更新

- 接入 Rust 文档系统事件
- 支持 `created/updated/deleted`
- 支持按文档增量重建
- 支持失败重试与状态监控

## 12. 总结

BizAgentPlatform 的知识库方案建议采用“分层入库 + 统一索引 + 统一检索 + 事件驱动增量更新”的架构。

核心原则如下：

- 文本类、复杂 PDF、Excel 分 pipeline 处理
- Corpus 与 Chunk 统一使用 JSONL
- 检索层统一使用 Milvus
- 平台层统一封装 `retrieve`
- Rust 文档系统通过事件驱动方式触发增量写入

按这个方案推进，可以先快速上线基本知识库能力，再逐步演进到多来源、可增量、可追踪、可运维的企业知识平台。
