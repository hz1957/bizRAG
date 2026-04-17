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
- `bizrag.service.retrieve_api`：对外暴露 `POST /api/v1/retrieve`
- `benchmark` / `evaluation`：支持基础离线评测

当前仍然存在的限制：

- 知识库元数据已经有 SQLite 持久化层，但还没有独立服务化存储
- 已支持目录扫描、文档删除、集合重建，但当前索引更新仍以 KB 级重建为主
- 已落 `retrieve` 和最小规则式 `extract` API，但还没有接入生成式抽取模型
- 评测能力已接入项目，但还没有形成正式业务评测集

因此，当前项目不适合直接视为“已完成的平台服务”，更准确的状态是：Phase 1 已完成最小闭环，Phase 2 已进入知识库管理能力落地阶段。

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

### 5.1 文本类入库 Pipeline

适用于 `md/doc/docx/pdf/txt`：

```yaml
servers:
  corpus: bizrag/src/servers/corpus

pipeline:
- corpus.build_text_corpus
```

### 5.2 复杂 PDF 入库 Pipeline

```yaml
servers:
  corpus: bizrag/src/servers/corpus

pipeline:
- corpus.mineru_parse
- corpus.build_mineru_corpus
```

### 5.3 Excel 入库 Pipeline

```yaml
servers:
  biz_corpus: bizrag/src/servers/biz_corpus

pipeline:
- biz_corpus.build_excel_corpus
```

### 5.4 Chunk Pipeline

```yaml
servers:
  corpus: bizrag/src/servers/corpus

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
  retriever: bizrag/src/servers/retriever

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
kb_id -> collection_name
query -> structured retriever
filters -> milvus filter
ret_items -> 业务结构化包装
```

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

- 已开始落地
- 代码已接入项目
- 仍需真实依赖与真实数据联调

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

- 已新增 `bizrag.service.kb_admin`
- 已新增 SQLite 元数据存储：`bizrag/state/metadata.db`
- 已支持 `register-kb`、`ingest-path`、`delete-document`、`rebuild-kb`、`retry-task`
- 已支持目录扫描、内容 hash 去重、文档级 corpus/chunk 产物、集合级重建
- 已支持自动同步 `bizrag/config/kb_registry.yaml`

当前命令示例：

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

```bash
python -m bizrag.service.kb_admin \
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

### Phase 4：生产化与运维能力

目标：把服务推进到平台正式接入所需的稳定度。

包括：

- 补监控、日志、trace、告警
- 补缓存、限流、超时、重试
- 做多租户与权限隔离
- 增加健康检查、容量与成本治理
- 建立 CI/CD、回归测试和回滚流程

交付结果：

- 服务可稳定运行
- 出问题可定位、可回滚
- 具备正式接入条件
