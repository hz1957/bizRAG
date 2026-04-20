# 手工联调命令（放到 test/ 里直接跑）

前置：
```bash
cd /Users/haoming.zhang/PyCharmMiscProject/bizRAG
export BIZRAG_API=http://127.0.0.1:64501
export FILE_SERVICE_API=http://127.0.0.1:8002
export KB_ID="manual_file_test_$(date +%s)"
```

1. 启动服务（按你当前 compose 典型配置）：
```bash
docker compose up -d mysql rabbitmq milvus file_service bizrag
```

2. 检查 BizRAG 是否有 `openpyxl`（没有就先装）：
```bash
docker exec bizrag-bizrag-1 python -c "import openpyxl, importlib.util; print(openpyxl.__version__)"
# 如果报错安装
docker exec bizrag-bizrag-1 python -m pip install --no-cache-dir openpyxl
```

3. 在 BizRAG 注册一个测试 KB（注意这里必须用容器内路径）：
```bash
curl -s -X POST "$BIZRAG_API/api/v1/admin/kbs/register" \
  -H "Content-Type: application/json" \
  -d "{\"kb_id\":\"$KB_ID\",\"retriever_config\":\"/app/bizrag/servers/retriever/parameter.docker.yaml\",\"collection_name\":\"$KB_ID\"}"
```

4. 用 `file_service` 上传一个文件（`xlsx`）：
```bash
TEST_FILE="runtime/file_service/watch/计算模板RAG/1. CV telemetry study in jacketed Rats.new.xlsx"
UP_RET=$(curl -s -X POST "$FILE_SERVICE_API/api/v1/files/" \
  -F kb_id=$KB_ID \
  -F tenant_id=default \
  -F file_name="manual_contract.xlsx" \
  -F "file=@${TEST_FILE}")
echo "$UP_RET" | python -c "import sys,json; print(json.load(sys.stdin))"
export FILE_ID=$(echo "$UP_RET" | python -c "import sys,json; print(json.load(sys.stdin)['file_id'])")
export DOC_EVENT_ID=$(echo "$UP_RET" | python -c "import sys,json; print(json.load(sys.stdin)['event']['event_id'])")
echo "FILE_ID=$FILE_ID DOC_EVENT_ID=$DOC_EVENT_ID"
```

5. 在 BizRAG 看事件是否写成功（看是否 `success`）：
```bash
curl -s "$BIZRAG_API/api/v1/admin/events?kb_id=$KB_ID&limit=20" | python -m json.tool
```

6. 触发一次更新（document.updated）：
```bash
UPDATE_RET=$(curl -s -X PUT "$FILE_SERVICE_API/api/v1/files/$FILE_ID/content" \
  -F file_name="manual_contract_updated.xlsx" \
  -F "file=@${TEST_FILE}")
echo "$UPDATE_RET" | python -c "import sys,json; print(json.load(sys.stdin)['event']['event_id'])"
export UPDATE_EVENT_ID=$(echo "$UPDATE_RET" | python -c "import sys,json; print(json.load(sys.stdin)['event']['event_id'])")
```

7. 查看最近事件并筛出失败项（如有）：
```bash
curl -s "$BIZRAG_API/api/v1/admin/events?kb_id=$KB_ID&limit=50" \
  | python - <<'PY'
import json,sys
data=json.load(sys.stdin)
for it in data.get("items",[]):
    if it.get("status")!="success":
        print(f"{it['event_id']} {it['event_type']} {it['status']} {it.get('error_message')}")
PY
```

8. 删除文件（document.deleted）：
```bash
curl -s -X DELETE "$FILE_SERVICE_API/api/v1/files/$FILE_ID" | python -c "import sys,json; print(json.load(sys.stdin))"
```

9. 按“旧事件 id”重放一条失败事件（若上一步显示有失败 id 就替换成你那条）：
```bash
FAILED_ID="<把上一步失败的 event_id 贴进来>"
curl -s -X POST "$BIZRAG_API/api/v1/admin/events/${FAILED_ID}/replay"
```

10. 验证写入到 RAG（能返回内容即成功）：
```bash
curl -s -X POST "$BIZRAG_API/api/v1/retrieve" \
  -H "Content-Type: application/json" \
  -d "{\"kb_id\":\"$KB_ID\",\"query\":\"contract\",\"top_k\":3}"
```

备注：第 7 步里输出的 `event_id` 是 admin 事件 id，不是 file_service 的 file_id。重放时一定贴 admin 事件 id。
