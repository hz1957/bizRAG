# file_service

独立文件服务，位于 `bizrag` 外部。负责接收文件变更并把变更事件推送到 BizRAG MQ。

目标：你把文件先上传到这个服务，服务写入本地存储后，按 `document.created` / `document.updated` / `document.deleted` 事件推送到 `bizrag.rustfs.events`，BizRAG 原生 `mq_bridge -> worker` 会消费后触发现有写链路。

## 架构

- `API`：`file_service/app/api.py`
  - 上传：`POST /api/v1/files`
  - 更新文件内容：`PUT /api/v1/files/{file_id}/content`
  - 元数据变更：`PATCH /api/v1/files/{file_id}`
  - 删除：`DELETE /api/v1/files/{file_id}`
  - 查询：`GET /api/v1/files/{file_id}`
  - 版本列表：`GET /api/v1/files/{file_id}/versions`
  - 下载：`GET /api/v1/files/{file_id}/content`
- `Storage`：`file_service/app/storage.py`  
  以本地路径 `storage_root` 保存版本化文件（按 `tenant/file_id/version/<filename>` 组织）。
- `SQLite`：`file_service/app/db.py`  
  保存文件元数据、版本、发送队列（outbox）。
- `Publisher`：`file_service/app/publisher.py`
  - 默认把 outbox 中事件推到 RabbitMQ queue：`bizrag.rustfs.events`
  - 可切到 HTTP 直推 BizRAG 的 `/api/v1/events/rustfs/queue/batch`

## 事件兼容

每条事件都是 JSON 对象，字段对齐 BizRAG 的 `RustFSEventRequest`：

- `event_type`: `document.created|document.updated|document.deleted`
- `kb_id`
- `doc_id`: 本服务生成的 `file_id`
- `source_uri`: `filestore://{tenant_id}/{file_id}`
- `new_source_uri`: 同 `source_uri`
- `file_name`
- `content_type`
- `version`
- `content_hash`
- `download_url`: 指向本服务下载接口

事件先落入 `outbox_events`，由后台 publisher 定时发送，确保失败重试。

### 下载地址配置（关键）

`download_url` 由 `FILE_SERVICE_DOWNLOAD_BASE_URL` 决定，默认取自 `FILE_SERVICE_BASE_URL`。  
如果 BizRAG worker 与 file_service 不在同一网络（例如 BizRAG 在 Docker 内、file_service 在宿主机），请把该地址设置为 `worker` 可访问的地址，否则会出现 `Connection refused`（你日志里看到的错误）。

- 本机直接联调（host 上运行）：`FILE_SERVICE_DOWNLOAD_BASE_URL=http://127.0.0.1:8002`
- macOS Docker 到宿主机：`FILE_SERVICE_DOWNLOAD_BASE_URL=http://host.docker.internal:8002`
- Linux Docker 到宿主机：`FILE_SERVICE_DOWNLOAD_BASE_URL=http://172.17.0.1:8002` 或网卡网关对应 IP
- 两端都在同一容器网络：按网络内服务名/IP 配置 `FILE_SERVICE_DOWNLOAD_BASE_URL`

## 快速启动

```bash
cd /Users/haoming.zhang/PyCharmMiscProject/bizRAG
python -m pip install -r file_service/requirements.txt
cp file_service/.env.example file_service/.env
source file_service/.env
python -m file_service.run
```

### Docker 启动（推荐）

```bash
cd /Users/haoming.zhang/PyCharmMiscProject/bizRAG
docker compose up -d file_service
```

容器内建议挂载两个目录：

- `runtime/file_service/storage`：文件分片持久化目录
- `runtime/file_service/state`：sqlite 元数据（包括 outbox、file/version、事件状态）
- `runtime/file_service/watch`：本地监听目录（本地改动会触发事件）

监听目录挂载后，向该目录新增/修改/删除文件即可生成 `document.created / document.updated / document.deleted` 消息：

```bash
cp /path/to/doc.txt runtime/file_service/watch/doc.txt
```

默认监听地址：

- 服务：`http://127.0.0.1:8002`
- API 前缀：`/api/v1/files`

如你修改了 `FILE_SERVICE_BASE_URL`，请确认 `FILE_SERVICE_DOWNLOAD_BASE_URL` 已同步调整。

## 基础验证

```bash
# 健康检查
curl http://127.0.0.1:8002/api/v1/files/health

# 上传
curl -F "kb_id=test_kb" -F "tenant_id=tenant_a" -F "file_name=demo.txt" \
     -F "file=@/path/to/your/file.txt" http://127.0.0.1:8002/api/v1/files/
```

返回中的 `event_id` 应进入到 BizRAG MQ 队列（或 HTTP 事件入口）。

## 与 BizRAG 配合

1. 启动 `file_service`。
2. 配置 `FILE_SERVICE_RABBITMQ_URL` 与 `FILE_SERVICE_RABBITMQ_QUEUE` 指向 `bizrag` 的 RabbitMQ 队列（默认 `bizrag.rustfs.events`）。
3. 启动 BizRAG 的 `rustfs_mq_bridge` + `rustfs_worker`，保持现有环境变量中的 `RUSTFS_RABBITMQ_QUEUE` 一致。
4. 按上述接口上传/更新/删除文件，观察 BizRAG 侧 `rustfs_worker` 是否有 `ingest_file` / `delete_document` 事件执行。
5. 若事件失败，先检查 `admin/events` 中状态是否 `success`，再检查 `download_url` 是否可被 BizRAG 容器访问。

### 目录监听关键变量

在 `file_service/.env.example` 中已内置：

- `FILE_SERVICE_WATCH_ENABLED`：总开关
- `FILE_SERVICE_WATCH_ROOT`：监听目录（在容器内建议 `/data/watch`）
- `FILE_SERVICE_WATCH_KB_ID`：监听文件落库到的 kb_id
- `FILE_SERVICE_WATCH_TENANT_ID`：监听文件 tenant_id
- `FILE_SERVICE_WATCH_RECURSIVE`：是否递归
- `FILE_SERVICE_WATCH_INITIAL_SCAN`：启动时是否扫描既有文件
- `FILE_SERVICE_WATCH_DEBOUNCE_SECONDS`：事件抖动等待（秒）
- `FILE_SERVICE_WATCH_DELETE_SYNC`：删除时是否推送 `document.deleted`

## 联调（可快速验收）

### 方案 A：不依赖 RabbitMQ（推荐先跑）

使用本仓库内置的 HTTP 桥接联调脚本，启动一个模拟 BizRAG 接口，验证事件是否发出且 outbox 成功出队。

```bash
cd /Users/haoming.zhang/PyCharmMiscProject/bizRAG
python file_service/scripts/e2e_http_bridge_smoke.py
```

脚本成功返回 `e2e-ok` 表示：

- 成功创建文件
- 成功更新文件内容
- 成功删除文件
- 三类事件（created / updated / deleted）都推到了模拟 BizRAG HTTP 接口
- `file_service` 的 outbox 事件状态为 `published`

### 方案 B：接入真实 BizRAG MQ 链路

1. 保持 BizRAG 运行（含 `rustfs_mq_bridge` 与 `rustfs_worker`）。
2. 配置 `FILE_SERVICE_PUBLISHER_BACKEND=rabbitmq`。
3. 将 `FILE_SERVICE_RABBITMQ_URL`、`FILE_SERVICE_RABBITMQ_QUEUE` 与 BizRAG 的 `RABBITMQ_URL / RUSTFS_RABBITMQ_QUEUE` 保持一致（默认 `bizrag.rustfs.events`）。
4. 在 BizRAG 侧确认事件入队并成功被 worker 处理（`rustfs_events.status = 'success'`）。
5. 若使用 `scripts/rabbitmq_e2e.sh`，先确保 BizRAG 侧在临时环境可注册 KB；然后改为通过 file_service 的上传接口触发消息即可。

## 目录

- `app/config.py`：环境变量与服务配置
- `app/db.py`：SQLite 元数据与 outbox
- `app/storage.py`：版本化文件落盘
- `app/api.py`：HTTP 路由
- `app/publisher.py`：outbox 消费与 MQ 发布
- `run.py`：uvicorn 启动入口
