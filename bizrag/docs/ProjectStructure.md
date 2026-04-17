# bizRAG 项目架构说明

本项目基于 UltraRAG 底层框架进行二次开发，旨在为 BizAgent 智能体平台提供企业级知识库解析、检索和抽取服务。当前仓库已经完成一轮包结构收敛，核心 Python 包统一落在 `bizrag/` 目录下。

以下是详细的项目层级及文件职能拆解：

## bizrag (核心业务目录)
包含对外 SDK、HTTP API、应用服务、基础设施适配、底层 server 实现、pipeline 配置和项目内文档。

### sdk.py
- **职能**：执行桥接器 (Pipeline Runner)。
- **说明**：将上层服务传递过来的 Python 参数，动态拼装并覆盖到底层的 YAML 配置上，从而驱动本地 pipeline 执行。对外统一使用 `from bizrag.sdk import ...`。

### api (HTTP 接入层)
- **职能**：承载 FastAPI 应用、路由、HTTP 依赖注入和错误收口。
- **说明**：真正的 HTTP 路由定义在 `bizrag/api/routers/*`，应用装配在 `bizrag/api/app.py`，进程入口位于 `bizrag/entrypoints/retrieve_api.py`。
##### app.py
- **职能**：创建 `FastAPI` 应用并注册各类路由。
##### deps.py
- **职能**：统一装配 `KBAdmin`、检索服务和 API 运行时配置。
##### schemas.py
- **职能**：兼容导出 HTTP 层使用的 schema；共享模型的真实定义已迁到 `bizrag/contracts/schemas.py`。
##### routers/retrieve.py
- **职能**：提供 `/healthz`、`/api/v1/retrieve`、`/api/v1/extract`。
##### routers/admin.py
- **职能**：提供知识库管理、任务查询和事件重放接口。
##### routers/rustfs.py
- **职能**：提供 RustFS webhook、批量接入和入队接口。

### contracts (共享契约层)
- **职能**：承载 API、worker、MQ bridge 共同依赖的请求/响应模型与字段常量。
- **说明**：用于避免 `service -> api` 的反向依赖，让 HTTP 适配层和后台进程都依赖同一份契约定义。
##### schemas.py
- **职能**：集中定义 `retrieve/extract/admin/rustfs` 的共享模型和 `DEFAULT_OUTPUT_FIELDS`。

### service (业务服务层)
- **职能**：承载应用层逻辑与业务编排，不直接暴露 HTTP 路由。
- **约束**：默认遵循 `service -> orchestrator -> sdk -> pipelines -> servers`。
- **说明**：写链路不应直接 import `servers` 执行业务动作，而应通过编排层驱动 pipeline；在线读链路如 `retrieve/extract` 可保留直连封装服务，但不应在 `service` 中散落底层算子调用。
##### kb_admin.py
- **职能**：知识库管理员中控台。提供创立知识库、接收文件导入指令、触发入库与全文向量索引重建的逻辑。
- **说明**：当前已按 `pipeline-first` 收敛，导入、chunk、增量索引、删除和重建均通过 `service/orchestrator.py` 调用 pipelines。
##### orchestrator.py
- **职能**：服务编排适配层。
- **说明**：负责把 `service` 侧的业务动作翻译为稳定的 pipeline 调用，屏蔽 YAML 名称、参数格式和底层 server 细节，是 `pipeline-first` 约束的落点。
##### retrieval_service.py
- **职能**：在线检索应用服务。
- **说明**：封装 `Retriever` 的延迟初始化、检索执行和命中结果标准化，供 API 层调用。
##### rustfs_event_service.py
- **职能**：RustFS 事件应用服务。
- **说明**：封装签名校验、payload 落地、事件处理、入队和重放逻辑，供 API、worker 和 MQ bridge 复用。
##### rustfs_worker.py
- **职能**：RustFS worker 兼容入口包装。
- **说明**：真实进程入口已迁到 `bizrag.entrypoints.rustfs_worker`；当前文件仅保留兼容导出。
##### rustfs_mq_bridge.py
- **职能**：RustFS MQ bridge 兼容入口包装。
- **说明**：真实进程入口已迁到 `bizrag.entrypoints.rustfs_mq_bridge`；当前文件仅保留兼容导出。
##### extract_engine.py
- **职能**：RAG 抽取引擎。负责对检索后的事实片段进行规则化或后续模型化处理，提炼结构化业务洞察。
##### errors.py
- **职能**：服务层错误类型定义。
- **说明**：统一承载 `BadRequest / Unauthorized / NotFound / ServiceUnavailable` 等非 HTTP 业务异常，供 API 层映射为 `HTTPException`。

### entrypoints (进程入口层)
- **职能**：承载 API、worker、MQ bridge 的 CLI 启动入口。
- **说明**：用于把“进程启动逻辑”从 `service` 中抽离，避免业务层继续混入参数解析和进程编排。
##### retrieve_api.py
- **职能**：加载 API 配置并启动 Uvicorn。
##### rustfs_worker.py
- **职能**：启动 RustFS 持久化事件 worker。
##### rustfs_mq_bridge.py
- **职能**：启动 Kafka / RabbitMQ 到本地事件队列的桥接进程。

### infra (基础设施适配层)
- **职能**：承载数据库、消息系统等基础设施适配实现。
##### metadata_store.py
- **职能**：知识库元数据库操作层。记录 KB、文档、任务和 RustFS 事件状态，管理防重入库和事件补偿的幂等逻辑。
- **说明**：当前已支持 `SQLite / MySQL` 双后端；默认仍可使用本地 `metadata.db`，Phase 5 可切到 MySQL 作为正式控制面存储。

### servers (底层处理插件节点 / MCP Servers)
- **职能**：定义细粒度、单一职责的 “加工组件模型” (例如专门只为切块，或者只读 Excel 写的逻辑)。
##### biz_corpus
- **职能**：为 BizAgent 独家优化的语料预处理器，内部如 `biz_corpus.py` 包含读取并解析复杂多 sheet Excel 文件的特化处理。
##### corpus
- **职能**：基础语料处理器与分块器，底层实现各种基础文本与 PDF `mineru` 的切分与抽取。
##### retriever
- **职能**：向量召回处理集合。负责连接底层数据库（如 Milvus），实现 Embedding 的转化与查询匹配。
##### benchmark
- **职能**：算法基准测试模块。用于跑测试指标并打分。
##### evaluation
- **职能**：评测执行模块。负责检索指标与结构化抽取指标计算。

### pipelines (流水线与工作流编排层)
声明式的 YAML 工作流集结地，将 `servers` 里的底层算子打通为自动化管线。

- **架构地位**：这是写链路的唯一标准编排层。
- **约束**：凡是导入、chunk、index、delete、drop collection、rebuild、evaluation 这类多步骤动作，优先新增或复用 pipeline，而不是在 `service` 里直接串底层 server。

#### build_text_corpus.yaml
- **职能**：最常用的普通文本以及纯文字版 PDF 等常规文档的执行流水线。
#### build_mineru_corpus.yaml
- **职能**：带大量复杂图表、公式版面的重度 PDF 的独立执行流水线。
#### build_excel_corpus.yaml
- **职能**：企业内大量使用的各类 Excel 表格类数据的专属解析流水线。
#### corpus_chunk.yaml
- **职能**：将大段结构化语料拆解为适合灌库的 Token 向量大小片段的切块流水线。
#### milvus_index.yaml / milvus_delete.yaml / milvus_drop_collection.yaml
- **职能**：承接向量索引写入、按文档删除和集合删除，是知识库写链路的标准索引编排入口。

### config (项目微调配置档)
- **职能**：启动测试、算法微调所需的独立参配。
#### retriever_phase1_local.yaml
- **职能**：提供在阶段一召回开发测试时的人工评测入参参数大全。

### docs (项目内文档)
- **职能**：维护 BizRAG 自己的架构说明、平台接入方案和阶段规划。

---

## scripts (联调脚本)
这些脚本用于快速复现平台接入或端到端联调流程。

### rabbitmq_e2e.sh
- **职能**：一键跑通 `RabbitMQ -> mq_bridge -> SQLite queue -> rustfs_worker -> BizRAG 检索验证` 的联调脚本。
### ci_smoke_rabbitmq.sh
- **职能**：CI 场景用的 RabbitMQ smoke test 入口脚本，负责安装依赖并调用 `rabbitmq_e2e.sh`。

### state (项目内状态)
- **职能**：保存项目级状态数据。
#### metadata.db
- **职能**：默认本地 SQLite 元数据数据库，记录 KB、文档和任务状态；Phase 5 也可由 MySQL 取代为正式元数据存储。

## docker (Phase 5 部署模板)
- **职能**：承载 Phase 5 的容器化部署入口。
### Dockerfile
- **职能**：构建 `bizrag` 应用镜像，包含 API、MQ bridge、worker 运行环境。
### start_bizrag.sh
- **职能**：容器启动脚本，在单容器内拉起 `retrieve_api`、`rustfs_mq_bridge` 和 `rustfs_worker`。

## docker-compose.yml
- **职能**：Phase 5 第一版标准部署拓扑模板，覆盖 `rustfs`、`rabbitmq`、`milvus`、`mysql`、`bizrag` 五类容器。

---

## 仓库根目录运行数据
这些目录不属于 Python 包本身，但属于 BizRAG 运行时的重要组成部分。

### runtime
- **职能**：存储各知识库运行时产物，如合并后的 corpus/chunks、embedding 文件和索引配置。
#### kbs
- **职能**：各个知识库租户专属的数据目录。

## logs (项目外部根目录日志)
引擎启动和处理文件时产生的终端输出流。放在根目录为防止与持久化源码混淆。

## output (项目外部根目录产物)
评测结果产出目录。
### phase1
- **职能**：如 `run.txt`, `qrels.txt`, `eval_results.json`，均属于打分算法执行完毕对本系统检索准确率客观量化评估留存的数据文件。

## raw_knowledge (项目外部根目录原始知识源)
- **职能**：存放业务原始文档样本，用于导入和联调。

---

## 架构约束

为避免代码再次回退到 `service` 直调 `servers` 的耦合模式，当前项目约定如下：

1. 写链路默认使用 `pipeline-first`
   - 标准路径：`service -> orchestrator -> sdk -> pipelines -> servers`
   - 适用范围：`ingest`、`chunk`、`index`、`delete`、`rebuild`、`evaluation`

2. `service` 不直接承载底层算子编排
   - `api` 负责 HTTP 协议适配、参数解析和错误收口
   - `service` 负责应用逻辑和业务编排
   - 不应在 `service` 内直接拼装 `corpus`、`retriever`、`biz_corpus` 等底层执行步骤

3. `servers` 只提供原子能力
   - `servers` 目录中的实现不感知平台请求、不承担业务流程编排
   - 新增底层能力时，优先补对应 pipeline，而不是把调用逻辑塞进 `service`

4. 在线读链路允许例外
   - `retrieve/extract` 这类低延迟读链路当前可直接走封装后的服务对象
   - 但若出现多步骤读链路，也应先评估是否应抽成统一编排层

5. 新增写链路功能时的默认顺序
   - 先补 `pipelines/*.yaml`
   - 再补 `sdk.py` / `service/orchestrator.py`
   - 最后由 `service` 接入

---

## reference (参考与原生档案)
从官方 UltraRAG 隔离出的大小样板，不直接参与目前正式业务的运行。

### examples
- **职能**：官方提供的各类 Pipeline 和参数排列组合的满级示例。
### prompt
- **职能**：官方默认带的各种语言的系统提示词资源文件。
### script
- **职能**：官方携带的外部处理、评测等辅助 Python 小脚本。
### docs
- **职能**：`Docs.md`, `SDKReference.md` 等底层原生的参考文档及签名资料。
