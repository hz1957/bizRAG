> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# 部署指南

本指南将指导您完成 UltraRAG UI 的全栈部署，包括生成模型（LLM）、检索模型（Embedding）以及 Milvus 向量数据库。

## 模型推理服务部署

UltraRAG UI 统一采用 OpenAI API 协议进行调用。您可以选择直接在宿主机使用 `Screen` 运行，或使用 `Docker` 容器化部署。

### 生成模型部署

以 Qwen3-32B 为例，建议使用多卡并行以保证推理速度。

**Screen (宿主机直接运行)**

1. 新建会话会话：

```shell theme={null}
screen -S llm
```

2. 启动命令：

```shell script/vllm_serve.sh theme={null}
CUDA_VISIBLE_DEVICES=0,1 python -m vllm.entrypoints.openai.api_server \
    --served-model-name qwen3-32b \
    --model Qwen/Qwen3-32B \
    --trust-remote-code \
    --host 0.0.0.0 \
    --port 65503 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.9 \
    --tensor-parallel-size 2 \
    --enforce-eager
```

出现类似以下输出，表示模型服务启动成功：

```
(APIServer pid=2811812) INFO:     Started server process [2811812]
(APIServer pid=2811812) INFO:     Waiting for application startup.
(APIServer pid=2811812) INFO:     Application startup complete.
```

3. 退出会话：按下 `Ctrl + A + D` 可退出并保持服务在后台运行。
   如需重新进入该会话，可执行：

```shell theme={null}
screen -r llm
```

**Docker (容器化部署)**

```shell theme={null}
docker run -d --gpus all \
  -e CUDA_VISIBLE_DEVICES=0,1 \
  -v /parent_dir_of_models:/workspace \
  -p 29001:65503 \
  --ipc=host \
  --name vllm_qwen \
  vllm/vllm-openai:latest \
  --served-model-name qwen3-32b \
  --model Qwen/Qwen3-32B \
  --trust-remote-code \
  --host 0.0.0.0 \
  --port 65503 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.9 \
  --tensor-parallel-size 2 \
  --enforce-eager
```

### 检索模型部署

以 Qwen3-Embedding-0.6B 为例，通常占用显存较小。

**Screen (宿主机直接运行)**

1. 新建会话：

```shell theme={null}
screen -S retriever
```

2. 启动命令：

```shell script/vllm_serve_emb.sh theme={null}
CUDA_VISIBLE_DEVICES=2 python -m vllm.entrypoints.openai.api_server \
    --served-model-name qwen-embedding \
    --model Qwen/Qwen3-Embedding-0.6B \
    --trust-remote-code \
    --host 0.0.0.0 \
    --port 65504 \
    --task embed \
    --gpu-memory-utilization 0.2
```

**Docker (容器化部署)**

```shell theme={null}
docker run -d --gpus all \
  -e CUDA_VISIBLE_DEVICES=2 \
  -v /parent_dir_of_models:/workspace \
  -p 29002:65504 \
  --ipc=host \
  --name vllm_qwen_emb \
  vllm/vllm-openai:latest \
  --served-model-name qwen-embedding \
  --model Qwen/Qwen3-Embedding-0.6B \
  --trust-remote-code \
  --host 0.0.0.0 \
  --port 65504 \
  --task embed \
  --gpu-memory-utilization 0.2
```

## 向量数据库部署 (Milvus)

Milvus 用于高效存储和检索向量数据。

**官方部署**

```shell theme={null}
# milvus单机版（docker）：https://milvus.io/docs/zh/install-overview.md#Milvus-Standalone
curl -sfL https://raw.githubusercontent.com/milvus-io/milvus/master/scripts/standalone_embed.sh -o standalone_embed.sh
bash standalone_embed.sh start
```

**自定义部署**

若需自定义端口（如防止端口冲突）或数据路径，可使用以下脚本：

```shell start_milvus.sh highlight="7,8,10" theme={null}
#!/usr/bin/env bash
set -e

CONTAINER_NAME=milvus-ultrarag
MILVUS_IMAGE=milvusdb/milvus:latest

GRPC_PORT=29901
HTTP_PORT=29902

DATA_DIR=/root/ultrarag-demo/milvus/

echo "==> Starting Milvus (standalone)"
echo "==> gRPC: ${GRPC_PORT}, HTTP: ${HTTP_PORT}"
echo "==> Data dir: ${DATA_DIR}"

mkdir -p ${DATA_DIR}
chown -R 1000:1000 ${DATA_DIR} 2>/dev/null || true

docker run -d \
  --name ${CONTAINER_NAME} \
  --restart unless-stopped \
  --security-opt seccomp:unconfined \
  -e DEPLOY_MODE=STANDALONE \
  -e ETCD_USE_EMBED=true \
  -e COMMON_STORAGETYPE=local \
  -v ${DATA_DIR}:/var/lib/milvus \
  -p ${GRPC_PORT}:19530 \
  -p ${HTTP_PORT}:9091 \
  --health-cmd="curl -f http://localhost:9091/healthz" \
  --health-interval=30s \
  --health-start-period=60s \
  --health-timeout=10s \
  --health-retries=3 \
  ${MILVUS_IMAGE} \
  milvus run standalone

echo "==> Waiting for Milvus to become healthy..."
sleep 5
docker ps | grep ${CONTAINER_NAME} || true
```

修改GRPC\_PORT、HTTP\_PORT以及DATA\_DIR，并运行以下命令进行部署：

```shell theme={null}
bash start_milvus.sh
```

部署成功后，您可以通过以下命令检查Milvus的状态：

```shell theme={null}
docker ps | grep milvus-ultrarag
```

如果一切正常，您应该能够看到Milvus容器正在运行。

<Tip>UI 配置提示：启动成功后，在 UltraRAG UI 的 `Knowledge Base` -> `Configure DB` 中填写 `GRPC_PORT` 地址（如 `tcp://127.0.0.1:29901`）。点击 Connect 显示 Connected 即代表成功。</Tip>

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Corpus

## `build_text_corpus`

**签名**

```python theme={null}
@app.tool(output="parse_file_path,text_corpus_save_path->None")
async def build_text_corpus(parse_file_path: str, text_corpus_save_path: str) -> None
```

**功能**

* 支持 .txt / .md；
* 支持 .docx（读取段落与表格内容）；
* 支持 .pdf / .xps / .oxps / .epub / .mobi / .fb2（经 pymupdf 纯文本抽取）。
* 目录模式下会递归处理。

**输出格式（JSONL）**

```json theme={null}
{"id": "<stem>", "title": "<stem>", "contents": "<全文文本>"}
```

***

## `build_image_corpus`

**签名**

```python theme={null}
@app.tool(output="parse_file_path,image_corpus_save_path->None")
async def build_image_corpus(parse_file_path: str, image_corpus_save_path: str) -> None
```

**功能**

* **仅支持 PDF**：以 144DPI 渲染每页为 JPG（RGB），并校验文件有效性。
* 目录模式下会递归处理。

**输出索引（JSONL）**

```json theme={null}
{"id": 0, "image_id": "paper/page_0.jpg", "image_path": "image/paper/page_0.jpg"}
```

***

## `mineru_parse`

**签名**

```python theme={null}
@app.tool(output="parse_file_path,mineru_dir,mineru_extra_params->None")
async def mineru_parse(
    parse_file_path: str, 
    mineru_dir: str, 
    mineru_extra_params: Optional[Dict[str, Any]] = None
) -> None
```

**功能**

* 调用 CLI `mineru` 对 PDF/目录进行结构化解析，输出到 `mineru_dir`。

***

## `build_mineru_corpus`

**签名**

```python theme={null}
@app.tool(output="mineru_dir,parse_file_path,text_corpus_save_path,image_corpus_save_path->None")
async def build_mineru_corpus(
    mineru_dir: str, 
    parse_file_path: str, 
    text_corpus_save_path: str, 
    image_corpus_save_path: str
) -> None
```

**功能**

* 汇总 MinerU 解析产物为 **文本语料 JSONL** 与 **图片索引 JSONL**。

**输出格式（JSONL）**

* 文本：

```json theme={null}
{"id": "<stem>", "title": "<stem>", "contents": "<markdown全文>"}
```

* 图片：

```json theme={null}
{"id": 0, "image_id": "paper/page_0.jpg", "image_path": "images/paper/page_0.jpg"}
```

***

## `chunk_documents`

**签名**

```python theme={null}
@app.tool(output="raw_chunk_path,chunk_backend_configs,chunk_backend,tokenizer_or_token_counter,chunk_size,chunk_path,use_title->None")
async def chunk_documents(
    raw_chunk_path: str,
    chunk_backend_configs: Dict[str, Any],
    chunk_backend: str = "token",
    tokenizer_or_token_counter: str = "character",
    chunk_size: int = 256,
    chunk_path: Optional[str] = None,
    use_title: bool = True,
) -> None
```

**功能**

* 将输入文本语料（JSONL，含 `id/title/contents`）按所选后端切分为段落块：
* Chunk Backend: 支持 `token` / `sentence` / `recursive`。
* Tokenizer: tokenizer\_or\_token\_counter 可选 `word`、`character` 或 `tiktoken` 编码名称（如 `gpt2`）。
* Chunk Size: 通过 `chunk_size` 控制块大小（overlap 默认为 size/4）。
* 可选在每个块首部附加文档标题（`use_title`）。

**输出格式（JSONL）**

```json theme={null}
{"id": 0, "doc_id": "paper", "title": "paper", "contents": "切块后的文本"}
```

***

## 参数配置

```yaml servers/corpus/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# servers/corpus/parameter.yaml
parse_file_path: data/UltraRAG.pdf
text_corpus_save_path: corpora/text.jsonl
image_corpus_save_path: corpora/image.jsonl

# mineru
mineru_dir: corpora/
mineru_extra_params:
  source: modelscope

# chunking parameters
raw_chunk_path: corpora/text.jsonl
chunk_path: corpora/chunks.jsonl
use_title: false
chunk_backend: sentence # choices=["token", "sentence", "recursive"]
tokenizer_or_token_counter: character
chunk_size: 512
chunk_backend_configs:
  token:
    chunk_overlap: 50
  sentence:
    chunk_overlap: 50
    min_sentences_per_chunk: 1
    delim: "['.', '!', '?', '；', '。', '！', '？', '\\n']"
  recursive:
    min_characters_per_chunk: 12
```

参数说明：

| 参数                           | 类型   | 说明                                                         |
| ---------------------------- | ---- | ---------------------------------------------------------- |
| `parse_file_path`            | str  | 输入文件或目录路径                                                  |
| `text_corpus_save_path`      | str  | 文本语料输出路径（JSONL）                                            |
| `image_corpus_save_path`     | str  | 图片语料索引输出路径（JSONL）                                          |
| `mineru_dir`                 | str  | MinerU 输出根目录                                               |
| `mineru_extra_params`        | dict | MinerU 额外参数，如 `source`、`layout` 等                          |
| `raw_chunk_path`             | str  | 切块输入文件路径（JSONL 格式）                                         |
| `chunk_path`                 | str  | 切块输出路径                                                     |
| `use_title`                  | bool | 是否在每个切块开头附加文档标题                                            |
| `chunk_backend`              | str  | 选择切块方式：`token`、`sentence`、`recursive`                      |
| `tokenizer_or_token_counter` | str  | 分词器或计数方式。可选：`word`, `character` 或 `tiktoken` 模型名（如 `gpt2`） |
| `chunk_size`                 | int  | 每个切块的目标大小                                                  |
| `chunk_backend_configs`      | dict | 各切块方法的配置项（见下）                                              |

`chunk_backend_configs` 详细参数：

| 后端类型          | 参数                         | 说明                        |
| ------------- | -------------------------- | ------------------------- |
| **token**     | `chunk_overlap`            | 块间重叠 token 数              |
| **sentence**  | `chunk_overlap`            | 块间重叠数                     |
|               | `min_sentences_per_chunk`  | 每个切块包含的最少句子数              |
|               | `delim`                    | 句子分隔符列表（字符串形式的 Python 列表） |
| **recursive** | `min_characters_per_chunk` | 递归切分时的最小字符单元              |

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Corpus

## `build_text_corpus`

**签名**

```python theme={null}
@app.tool(output="parse_file_path,text_corpus_save_path->None")
async def build_text_corpus(parse_file_path: str, text_corpus_save_path: str) -> None
```

**功能**

* 支持 .txt / .md；
* 支持 .docx（读取段落与表格内容）；
* 支持 .pdf / .xps / .oxps / .epub / .mobi / .fb2（经 pymupdf 纯文本抽取）。
* 目录模式下会递归处理。

**输出格式（JSONL）**

```json theme={null}
{"id": "<stem>", "title": "<stem>", "contents": "<全文文本>"}
```

***

## `build_image_corpus`

**签名**

```python theme={null}
@app.tool(output="parse_file_path,image_corpus_save_path->None")
async def build_image_corpus(parse_file_path: str, image_corpus_save_path: str) -> None
```

**功能**

* **仅支持 PDF**：以 144DPI 渲染每页为 JPG（RGB），并校验文件有效性。
* 目录模式下会递归处理。

**输出索引（JSONL）**

```json theme={null}
{"id": 0, "image_id": "paper/page_0.jpg", "image_path": "image/paper/page_0.jpg"}
```

***

## `mineru_parse`

**签名**

```python theme={null}
@app.tool(output="parse_file_path,mineru_dir,mineru_extra_params->None")
async def mineru_parse(
    parse_file_path: str, 
    mineru_dir: str, 
    mineru_extra_params: Optional[Dict[str, Any]] = None
) -> None
```

**功能**

* 调用 CLI `mineru` 对 PDF/目录进行结构化解析，输出到 `mineru_dir`。

***

## `build_mineru_corpus`

**签名**

```python theme={null}
@app.tool(output="mineru_dir,parse_file_path,text_corpus_save_path,image_corpus_save_path->None")
async def build_mineru_corpus(
    mineru_dir: str, 
    parse_file_path: str, 
    text_corpus_save_path: str, 
    image_corpus_save_path: str
) -> None
```

**功能**

* 汇总 MinerU 解析产物为 **文本语料 JSONL** 与 **图片索引 JSONL**。

**输出格式（JSONL）**

* 文本：

```json theme={null}
{"id": "<stem>", "title": "<stem>", "contents": "<markdown全文>"}
```

* 图片：

```json theme={null}
{"id": 0, "image_id": "paper/page_0.jpg", "image_path": "images/paper/page_0.jpg"}
```

***

## `chunk_documents`

**签名**

```python theme={null}
@app.tool(output="raw_chunk_path,chunk_backend_configs,chunk_backend,tokenizer_or_token_counter,chunk_size,chunk_path,use_title->None")
async def chunk_documents(
    raw_chunk_path: str,
    chunk_backend_configs: Dict[str, Any],
    chunk_backend: str = "token",
    tokenizer_or_token_counter: str = "character",
    chunk_size: int = 256,
    chunk_path: Optional[str] = None,
    use_title: bool = True,
) -> None
```

**功能**

* 将输入文本语料（JSONL，含 `id/title/contents`）按所选后端切分为段落块：
* Chunk Backend: 支持 `token` / `sentence` / `recursive`。
* Tokenizer: tokenizer\_or\_token\_counter 可选 `word`、`character` 或 `tiktoken` 编码名称（如 `gpt2`）。
* Chunk Size: 通过 `chunk_size` 控制块大小（overlap 默认为 size/4）。
* 可选在每个块首部附加文档标题（`use_title`）。

**输出格式（JSONL）**

```json theme={null}
{"id": 0, "doc_id": "paper", "title": "paper", "contents": "切块后的文本"}
```

***

## 参数配置

```yaml servers/corpus/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# servers/corpus/parameter.yaml
parse_file_path: data/UltraRAG.pdf
text_corpus_save_path: corpora/text.jsonl
image_corpus_save_path: corpora/image.jsonl

# mineru
mineru_dir: corpora/
mineru_extra_params:
  source: modelscope

# chunking parameters
raw_chunk_path: corpora/text.jsonl
chunk_path: corpora/chunks.jsonl
use_title: false
chunk_backend: sentence # choices=["token", "sentence", "recursive"]
tokenizer_or_token_counter: character
chunk_size: 512
chunk_backend_configs:
  token:
    chunk_overlap: 50
  sentence:
    chunk_overlap: 50
    min_sentences_per_chunk: 1
    delim: "['.', '!', '?', '；', '。', '！', '？', '\\n']"
  recursive:
    min_characters_per_chunk: 12
```

参数说明：

| 参数                           | 类型   | 说明                                                         |
| ---------------------------- | ---- | ---------------------------------------------------------- |
| `parse_file_path`            | str  | 输入文件或目录路径                                                  |
| `text_corpus_save_path`      | str  | 文本语料输出路径（JSONL）                                            |
| `image_corpus_save_path`     | str  | 图片语料索引输出路径（JSONL）                                          |
| `mineru_dir`                 | str  | MinerU 输出根目录                                               |
| `mineru_extra_params`        | dict | MinerU 额外参数，如 `source`、`layout` 等                          |
| `raw_chunk_path`             | str  | 切块输入文件路径（JSONL 格式）                                         |
| `chunk_path`                 | str  | 切块输出路径                                                     |
| `use_title`                  | bool | 是否在每个切块开头附加文档标题                                            |
| `chunk_backend`              | str  | 选择切块方式：`token`、`sentence`、`recursive`                      |
| `tokenizer_or_token_counter` | str  | 分词器或计数方式。可选：`word`, `character` 或 `tiktoken` 模型名（如 `gpt2`） |
| `chunk_size`                 | int  | 每个切块的目标大小                                                  |
| `chunk_backend_configs`      | dict | 各切块方法的配置项（见下）                                              |

`chunk_backend_configs` 详细参数：

| 后端类型          | 参数                         | 说明                        |
| ------------- | -------------------------- | ------------------------- |
| **token**     | `chunk_overlap`            | 块间重叠 token 数              |
| **sentence**  | `chunk_overlap`            | 块间重叠数                     |
|               | `min_sentences_per_chunk`  | 每个切块包含的最少句子数              |
|               | `delim`                    | 句子分隔符列表（字符串形式的 Python 列表） |
| **recursive** | `min_characters_per_chunk` | 递归切分时的最小字符单元              |

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Benchmark

## `get_data`

**签名**

```python theme={null}
@app.tool(output="benchmark->q_ls,gt_ls")
def get_data(benchmark: Dict[str, Any]) -> Dict[str, List[Any]]
```

**功能**

* 多格式加载：支持从本地加载 `.jsonl`、`.json` 或 `.parquet` 格式的评测数据集。
* 动态字段映射：利用 `key_map` 将原始数据中的不同列名（如 `question`, `answer`）统一映射为标准化输出键（通常为 `q_ls` 和 `gt_ls`）。
* 数据预处理：内置支持随机打乱（`shuffle`）与数量截断（`limit`）。
* Demo 里用来接收用户输入，将其视作一条数据（`q_ls`）。

**输出格式（JSON）**

```json theme={null}
{
  "q_ls": ["Question 1", "Question 2"],
  "gt_ls": [["Answer A1", "Answer A2"], ["Answer B"]]
}
```

***

## 参数配置

```yaml servers/benchmark/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  name: nq
  path: data/sample_nq_10.jsonl
  key_map:
    q_ls: question
    gt_ls: golden_answers
  shuffle: false
  seed: 42
  limit: -1
```

参数说明：

| 参数        | 类型      | 说明                                    |                                            |
| --------- | ------- | ------------------------------------- | ------------------------------------------ |
| `name`    | str     | 评测集名称，仅用于日志与标识（示例：`nq`）               |                                            |
| `path`    | str     | 数据文件路径，支持 `.jsonl`、`.json`、`.parquet` |                                            |
| `key_map` | dict    | 字段映射表，将原始字段映射为工具输出键                   |                                            |
|           | `q_ls`  | str                                   | 映射为 问题列表 的原始字段名（如文件中的 question 列）          |
|           | `gt_ls` | str                                   | 映射为 标准答案列表 的原始字段名（如文件中的 golden\_answers 列） |
| `shuffle` | bool    | 是否打乱样本顺序（默认 `false`）                  |                                            |
| `seed`    | int     | 随机种子（`shuffle=true` 时生效）              |                                            |
| `limit`   | int     | 采样数据条数上限。默认为 -1（加载全部），正整数表示截取前 N 条    |                                            |

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Retriever

## `retriever_init`

**签名**

```python theme={null}
async def retriever_init(
    model_name_or_path: str,
    backend_configs: Dict[str, Any],
    batch_size: int,
    corpus_path: str,
    gpu_ids: Optional[object] = None,
    is_multimodal: bool = False,
    backend: str = "sentence_transformers",
    index_backend: str = "faiss",
    index_backend_configs: Optional[Dict[str, Any]] = None,
    is_demo: bool = False,
    collection_name: str = "",
) -> None
```

**功能**

* 初始化检索服务。
* Embedding Backend (backend): 负责将文本/图像转换为向量 (Infinity, SentenceTransformers, OpenAI, BM25)。
* Index Backend (index\_backend): 负责向量的存储与检索 (FAISS, Milvus)。
* Demo Mode: 若 is\_demo=True，强制使用 OpenAI + Milvus 配置，忽略部分参数。

***

## `retriever_embed`

**签名**

```python theme={null}
async def retriever_embed(
    embedding_path: Optional[str] = None,
    overwrite: bool = False,
    is_multimodal: bool = False,
) -> None
```

**功能**

* (非 Demo 模式) 批量计算语料库的向量表示，并保存为 .npy 文件。
* 仅适用于 Dense Retriever 后端（BM25 不支持）。

***

## `retriever_index`

**签名**

```python theme={null}
async def retriever_index(
    embedding_path: str,
    overwrite: bool = False,
    collection_name: str = "",
    corpus_path: str = ""
) -> None
```

**功能**

* 构建检索索引。
* FAISS: 读取 embedding\_path (.npy) 构建本地索引文件。
* Milvus / Demo: 读取 corpus\_path (.jsonl)，生成向量并插入到指定的 collection\_name 中。

***

## `retriever_search`

**签名**

```python theme={null}
async def retriever_search(
    query_list: List[str],
    top_k: int = 5,
    query_instruction: str = "",
    collection_name: str = "",
) -> Dict[str, List[List[str]]]
```

**功能**

* 对单条或多条查询进行检索。
* 自动处理查询向量化（添加 query\_instruction）并在指定 collection\_name (针对 Milvus) 或默认索引中查找 Top-K。

**输出格式（JSON）**

```json theme={null}
{"ret_psg": [["passage 1", "passage 2"], ["..." ]]} 
```

***

## `retriever_batch_search`

**签名**

```python theme={null}
async def retriever_batch_search(
    batch_query_list: List[List[str]],
    top_k: int = 5,
    query_instruction: str = "",
    collection_name: str = "",
) -> Dict[str, List[List[List[str]]]]
```

**功能**

* etriever\_search 的批处理版本，接受嵌套列表输入。

**输出格式（JSON）**

```json theme={null}
{"ret_psg_ls": [[["psg 1-1"], ["psg 1-2"]], [["psg 2-1"]]]}
```

***

## `bm25_index`

**签名**

```python theme={null}
async def bm25_index(
    overwrite: bool = False,
) -> None
```

**功能**

* 当 `backend="bm25"` 时，构建 BM25 稀疏索引并保存。

***

## `bm25_search`

**签名**

```python theme={null}
async def bm25_search(
    query_list: List[str],
    top_k: int = 5,
) -> Dict[str, List[List[str]]]
```

**功能**

* 基于 BM25 算法进行关键词检索。

**输出格式（JSON）**

```json theme={null}
{"ret_psg": [["passage 1", "passage 2"], ["..." ]]} 
```

***

## `retriever_deploy_search`

**签名**

```python theme={null}
async def retriever_deploy_search(
    retriever_url: str,
    query_list: List[str],
    top_k: int = 5,
    query_instruction: str = "",
) -> Dict[str, List[List[str]]]
```

**功能**

* 作为客户端，调用部署在 retriever\_url 的远程检索服务进行查询。

**输出格式（JSON）**

```json theme={null}
{"ret_psg": [["passage 1", "passage 2"], ["..." ]]} 
```

***

## `retriever_exa_search`

**签名**

```python theme={null}
async def retriever_exa_search(
    query_list: List[str],
    top_k: Optional[int] | None = 5,
    retrieve_thread_num: Optional[int] | None = 1,
) -> Dict[str, List[List[str]]]
```

**功能**

* 调用 **Exa** Web 检索（需要 `EXA_API_KEY`）。

**输出格式（JSON）**

```json theme={null}
{"ret_psg": [["snippet 1", "snippet 2"], ["..." ]]} 
```

***

## `retriever_tavily_search`

**签名**

```python theme={null}
async def retriever_tavily_search(
    query_list: List[str],
    top_k: Optional[int] | None = 5,
    retrieve_thread_num: Optional[int] | None = 1,
) -> Dict[str, List[List[str]]]
```

**功能**

* 调用 **Tavily** Web 检索（需要 `TAVILY_API_KEY`）。

**输出格式（JSON）**

```json theme={null}
{"ret_psg": [["snippet 1", "snippet 2"], ["..." ]]} 
```

***

## `retriever_zhipuai_search`

**签名**

```python theme={null}
async def retriever_zhipuai_search(
    query_list: List[str],
    top_k: Optional[int] | None = 5,
    retrieve_thread_num: Optional[int] | None = 1,
) -> Dict[str, List[List[str]]]
```

**功能**

* 调用 **智谱AI** `web_search`（需要 `ZHIPUAI_API_KEY`）。

**输出格式（JSON）**

```json theme={null}
{"ret_psg": [["snippet 1", "snippet 2"], ["..." ]]} 
```

***

## 参数配置

```yaml servers/retriever/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
model_name_or_path: openbmb/MiniCPM-Embedding-Light
corpus_path: data/corpus_example.jsonl
embedding_path: embedding/embedding.npy
collection_name: wiki

# Embedding Backend Configuration
backend: sentence_transformers # options: infinity, sentence_transformers, openai, bm25
backend_configs:
  infinity:
    bettertransformer: false
    pooling_method: auto
    model_warmup: false
    trust_remote_code: true
  sentence_transformers:
    trust_remote_code: true
    sentence_transformers_encode:
      normalize_embeddings: false
      encode_chunk_size: 256
      q_prompt_name: query
      psg_prompt_name: document
      psg_task: null
      q_task: null
  openai:
    model_name: text-embedding-3-small
    base_url: "https://api.openai.com/v1"
    api_key: "abc"
  bm25:
    lang: en
    save_path: index/bm25

# Index Backend Configuration
index_backend: faiss # options: faiss, milvus
index_backend_configs:
  faiss:
    index_use_gpu: True
    index_chunk_size: 10000
    index_path: index/index.index
  milvus:
    uri: index/milvus_demo.db # Local file for Lite, or http://host:port
    token: null
    id_field_name: id
    vector_field_name: vector
    text_field_name: contents
    index_params:
      index_type: AUTOINDEX
      metric_type: IP

batch_size: 16
top_k: 5
gpu_ids: "1"
query_instruction: ""
is_multimodal: false
overwrite: false
retrieve_thread_num: 1
retriever_url: "http://127.0.0.1:64501"
is_demo: false
```

参数说明：

| 参数                      | 类型   | 说明                                                        |
| ----------------------- | ---- | --------------------------------------------------------- |
| `model_name_or_path`    | str  | 检索模型路径或名称（如 HuggingFace 模型 ID）                            |
| `corpus_path`           | str  | 输入语料 JSONL 文件路径                                           |
| `embedding_path`        | str  | 向量文件保存路径（`.npy`）                                          |
| `collection_name`       | str  | Milvus 集合名称                                               |
| `backend`               | str  | 选择检索后端：`infinity`、`sentence_transformers`、`openai`、`bm25` |
| `index_backend`         | str  | 索引后端：`faiss`, `milvus`                                    |
| `backend_configs`       | dict | 各后端的参数配置（见下表）                                             |
| `index_backend_configs` | dict | 各索引后端的参数配置（见下表）                                           |
| `batch_size`            | int  | 向量生成或检索的批大小                                               |
| `top_k`                 | int  | 返回的候选段落数量                                                 |
| `gpu_ids`               | str  | 指定可见 GPU 设备，如 `"0,1"`                                     |
| `query_instruction`     | str  | 查询前缀（instruction-tuning 模型使用）                             |
| `is_multimodal`         | bool | 是否启用多模态嵌入（如图像）                                            |
| `overwrite`             | bool | 若已存在嵌入或索引文件是否覆盖                                           |
| `retrieve_thread_num`   | int  | 外部 Web 检索（Exa/Tavily/Zhipu）并发线程数                          |
| `retriever_url`         | str  | 部署 retriever server 的 url                                 |
| `is_demo`               | bool | 演示模式开关（强制使用 OpenAI+Milvus，简化配置）                           |

`backend_configs` 子项：

| 后端                         | 参数                             | 类型   | 说明                                      |
| -------------------------- | ------------------------------ | ---- | --------------------------------------- |
| **infinity**               | `bettertransformer`            | bool | 是否启用高效推理优化                              |
|                            | `pooling_method`               | str  | 池化方式（如 `auto`, `mean`）                  |
|                            | `model_warmup`                 | bool | 是否预加载模型到显存                              |
|                            | `trust_remote_code`            | bool | 是否信任远程代码（适用于自定义模型）                      |
| **sentence\_transformers** | `trust_remote_code`            | bool | 是否信任远程模型代码                              |
|                            | `sentence_transformers_encode` | dict | 编码详细参数，见下表                              |
| **openai**                 | `model_name`                   | str  | OpenAI 模型名称（如 `text-embedding-3-small`） |
|                            | `base_url`                     | str  | API 基地址                                 |
|                            | `api_key`                      | str  | OpenAI API 密钥                           |
| **bm25**                   | `lang`                         | str  | 语言（决定停用词与分词器）                           |
|                            | `save_path`                    | str  | BM25 稀疏索引的保存目录                          |

`sentence_transformers_encode` 参数：

| 参数                     | 类型   | 说明                        |
| ---------------------- | ---- | ------------------------- |
| `normalize_embeddings` | bool | 是否归一化向量                   |
| `encode_chunk_size`    | int  | 编码块大小（避免显存溢出）             |
| `q_prompt_name`        | str  | 查询模板名                     |
| `psg_prompt_name`      | str  | 段落模板名                     |
| `q_task`               | str  | 任务描述（针对特定模型需要指定 Task 的情况） |
| `psg_task`             | str  | 任务描述（针对特定模型需要指定 Task 的情况） |

`index_backend_configs` 参数：

| 后端     | 参数                  | 类型   | 说明                                 |
| ------ | ------------------- | ---- | ---------------------------------- |
| faiss  | index\_use\_gpu     | bool | 是否使用 GPU 构建和检索索引                   |
|        | index\_chunk\_size  | int  | 构建索引时的分批大小                         |
|        | index\_path         | str  | FAISS 索引文件的保存路径（.index）            |
| milvus | uri                 | str  | Milvus 连接地址（本地文件路径即启用 Milvus Lite） |
|        | token               | str  | 认证 Token（如需要）                      |
|        | id\_field\_name     | str  | 主键字段名（默认 id）                       |
|        | vector\_field\_name | str  | 向量字段名（默认 vector）                   |
|        | text\_field\_name   | str  | 文本内容字段名（默认 contents）               |
|        | id\_max\_length     | int  | 字符串主键的最大长度                         |
|        | text\_max\_length   | int  | 文本字段的最大长度（超过截断）                    |
|        | metric\_type        | str  | 距离度量方式（如 IP 内积, L2 欧式距离）           |
|        | index\_params       | Dict | 索引构建参数（如 index\_type: AUTOINDEX）   |
|        | search\_params      | Dict | 检索参数（如 nprobe 等）                   |
|        | index\_chunk\_size  | int  | 插入数据时的批处理大小                        |

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Reranker

## `reranker_init`

**签名**

```python theme={null}
async def reranker_init(
    model_name_or_path: str,
    backend_configs: Dict[str, Any],
    batch_size: int,
    gpu_ids: Optional[object] = None,
    backend: str = "infinity",
) -> None
```

**功能**

* 初始化重排后端与模型

***

## `reranker_rerank`

**签名**

```python theme={null}
async def reranker_rerank(
    query_list: List[str],
    passages_list: List[List[str]],
    top_k: int = 5,
    query_instruction: str = "",
) -> Dict[str, List[Any]]
```

**功能**

* 对候选段落进行**重排**：

**输出格式（JSON）**

```json theme={null}
{
  "rerank_psg": [
    ["best passage for q0", "..."],
    ["best passage for q1", "..."]
  ]
}
```

***

## 参数配置

```yaml servers/reranker/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
model_name_or_path: openbmb/MiniCPM-Reranker-Light
backend: sentence_transformers # options: infinity, sentence_transformers, openai
backend_configs:
  infinity:
    bettertransformer: false
    pooling_method: auto
    device: cuda
    model_warmup: false
    trust_remote_code: true
  sentence_transformers:
    device: cuda
    trust_remote_code: true
  openai:
    model_name: text-embedding-3-small
    base_url: "https://api.openai.com/v1"
    api_key: ""

gpu_ids: 0
top_k: 5
batch_size: 16
query_instruction: ""
```

参数说明：

| 参数                   | 类型      | 说明                                                   |
| -------------------- | ------- | ---------------------------------------------------- |
| `model_name_or_path` | str     | 模型路径或名称（本地或 HuggingFace 仓库）                          |
| `backend`            | str     | 选择后端类型：`infinity`、`sentence_transformers` 或 `openai` |
| `backend_configs`    | dict    | 各后端的专属参数设置                                           |
| `gpu_ids`            | str/int | 指定 GPU ID（可多卡，如 `"0,1"`）                             |
| `top_k`              | int     | 返回的重排结果数                                             |
| `batch_size`         | int     | 每批处理的样本数量                                            |
| `query_instruction`  | str     | 查询前缀提示，用于 prompt 工程或 query 修饰                        |

`backend_configs` 详细说明：

| 后端                         | 参数                  | 说明                         |
| -------------------------- | ------------------- | -------------------------- |
| **infinity**               | `device`            | 设备类型（cuda / cpu）           |
|                            | `bettertransformer` | 是否启用加速推理                   |
|                            | `pooling_method`    | 向量池化策略                     |
|                            | `model_warmup`      | 是否预热模型                     |
|                            | `trust_remote_code` | 是否信任远程代码（HuggingFace 模型必需） |
| **sentence\_transformers** | `device`            | 设备类型（cuda / cpu）           |
|                            | `trust_remote_code` | 是否信任远程代码                   |
| **openai**                 | `model_name`        | API 模型名称                   |
|                            | `base_url`          | API 访问地址                   |
|                            | `api_key`           | OpenAI API 密钥              |

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Prompt

## QA Prompts

### `qa_boxed`

**签名**

```python theme={null}
@app.prompt(output="q_ls,template->prompt_ls")
def qa_boxed(
    q_ls: List[str], 
    template: str | Path
) -> List[PromptMessage]
```

**功能**

基础问答 Prompt。

加载指定 Jinja2 模板，将问题列表中的每个问题渲染为 Prompt。

模板变量: `{{ question }}`

### `qa_boxed_multiple_choice`

**签名**

```python theme={null}
@app.prompt(output="q_ls,choices_ls,template->prompt_ls")
def qa_boxed_multiple_choice(
    q_ls: List[str],
    choices_ls: List[List[str]],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

多选问答 Prompt。

自动将选项列表格式化为 "A: ..., B: ..." 的形式并注入模板。

模板变量: `{{ question }}`, `{{ choices }}`

### `qa_rag_boxed`

**签名**

```python theme={null}
@app.prompt(output="q_ls,ret_psg,template->prompt_ls")
def qa_rag_boxed(
    q_ls: List[str], 
    ret_psg: List[str | Any], 
    template: str | Path
) -> list[PromptMessage]
```

**功能**

标准 RAG Prompt。

将检索到的段落列表拼接后注入模板。

模板变量: `{{ question }}`, `{{ documents }}`

### `qa_rag_boxed_multiple_choice`

**签名**

```python theme={null}
@app.prompt(output="q_ls,choices_ls,ret_psg,template->prompt_ls")
def qa_rag_boxed_multiple_choice(
    q_ls: List[str],
    choices_ls: List[List[str]],
    ret_psg: List[List[str]],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

带检索上下文的多选问答 Prompt。

模板变量: `{{ question }}`, `{{ documents }}`, `{{ choices }}`

***

## RankCoT Prompts

### `RankCoT_kr`

**签名**

```python theme={null}
@app.prompt(output="q_ls,ret_psg,kr_template->prompt_ls")
def RankCoT_kr(
    q_ls: List[str],
    ret_psg: List[str | Any],
    template: str | Path,
) -> list[PromptMessage]
```

**功能**

RankCoT 第一阶段：知识检索 (Knowledge Retrieval) Prompt。

模板变量: `{{ question }}`, `{{ documents }}`

### `RankCoT_qa`

**签名**

```python theme={null}
@app.prompt(output="q_ls,kr_ls,qa_template->prompt_ls")
def RankCoT_qa(
    q_ls: List[str],
    kr_ls: List[str],
    template: str | Path,
) -> list[PromptMessage]
```

**功能**

RankCoT 第二阶段：基于思维链的问答 Prompt。

模板变量: `{{ question }}`, `{{ CoT }}` (此处 CoT 通常为上一阶段生成的知识)

***

## IRCoT Prompts

### `ircot_next_prompt`

**签名**

```python theme={null}
@app.prompt(output="memory_q_ls,memory_ret_psg,template->prompt_ls")
def ircot_next_prompt(
    memory_q_ls: List[List[str | None]],
    memory_ret_psg: List[List[List[str]] | None],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

IRCoT (Interleaved Retrieval CoT) 迭代 Prompt 生成。

根据历史轮次的检索结果和思维链，构建下一轮的 Prompt。支持单轮与多轮历史拼接。

模板变量: `{{ documents }}`, `{{ question }}`, `{{ cur_answer }}`

***

## WebNote Prompts

### `webnote_init_page`

**签名**

```python theme={null}
@app.prompt(output="q_ls,plan_ls,webnote_init_page_template->prompt_ls")
def webnote_init_page(
    q_ls: List[str],
    plan_ls: List[str],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

WebNote Agent：初始化笔记页面。

模板变量: `{{ question }}`, `{{ plan }}`

### `webnote_gen_plan`

**签名**

```python theme={null}
@app.prompt(output="q_ls,webnote_gen_plan_template->prompt_ls")
def webnote_gen_plan(
    q_ls: List[str],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

WebNote Agent：生成搜索计划。

模板变量: `{{ question }}`

### `webnote_gen_subq`

**签名**

```python theme={null}
@app.prompt(output="q_ls,plan_ls,page_ls,webnote_gen_subq_template->prompt_ls")
def webnote_gen_subq(
    q_ls: List[str],
    plan_ls: List[str],
    page_ls: List[str],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

WebNote Agent：生成子问题。

模板变量: `{{ question }}`, `{{ plan }}`, `{{ page }}`

### `webnote_fill_page`

**签名**

```python theme={null}
@app.prompt(output="q_ls,plan_ls,page_ls,subq_ls,psg_ls,webnote_fill_page_template->prompt_ls")
def webnote_fill_page(
    q_ls: List[str],
    plan_ls: List[str],
    page_ls: List[str],
    subq_ls: List[str],
    psg_ls: List[Any],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

WebNote Agent：根据检索结果填充笔记。

模板变量: `{{ question }}`, `{{ plan }}`, `{{ sub_question }}`, `{{ docs_text }}`, `{{ page }}`

### `webnote_gen_answer`

**签名**

```python theme={null}
@app.prompt(output="q_ls,page_ls,webnote_gen_answer_template->prompt_ls")
def webnote_gen_answer(
    q_ls: List[str],
    page_ls: List[str],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

WebNote Agent：基于笔记生成最终答案。

模板变量: `{{ question }}`, `{{ page }}`

***

## Search-R1 & R1-Searcher

### `search_r1_gen`

**签名**

```python theme={null}
@app.prompt(output="prompt_ls,ans_ls,ret_psg,search_r1_gen_template->prompt_ls")
def search_r1_gen(
    prompt_ls: List[PromptMessage],
    ans_ls: List[str],
    ret_psg: List[str | Any],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

适用于 R1 风格的生成 Prompt。

截取 Top-3 检索段落注入上下文。

模板变量: `{{ history }}`, `{{ answer }}`, `{{ passages }}`

### `r1_searcher_gen`

**签名**

```python theme={null}
@app.prompt(output="prompt_ls,ans_ls,ret_psg,r1_searcher_gen_template->prompt_ls")
def r1_searcher_gen(
    prompt_ls: List[PromptMessage],
    ans_ls: List[str],
    ret_psg: List[str | Any],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

适用于 R1 Searcher 的生成 Prompt。

截取 Top-5 检索段落。

模板变量: `{{ history }}`, `{{ answer }}`, `{{ passages }}`

***

## Search-o1 Prompts

### `search_o1_init`

**签名**

```python theme={null}
@app.prompt(output="q_ls,searcho1_reasoning_template->prompt_ls")
def search_o1_init(
    q_ls: List[str],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

Search-O1 初始推理 Prompt。

模板变量: `{{ question }}`

### `search_o1_reasoning_indocument`

**签名**

```python theme={null}
@app.prompt(output="extract_query_list,ret_psg,total_reason_list,searcho1_refine_template->prompt_ls")
def search_o1_reasoning_indocument(
    extract_query_list: List[str], 
    ret_psg: List[List[str]],       
    total_reason_list: List[List[str]], 
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

Search-O1 推理细化 Prompt。

将历史推理步骤（首步 + 末尾3步）与当前检索文档合并，用于下一步推理。

模板变量: `{{ prev_reasoning }}`, `{{ search_query }}`, `{{ document }}`

### `search_o1_insert`

**签名**

```python theme={null}
@app.prompt(output="q_ls,total_subq_list,total_final_info_list,searcho1_reasoning_template->prompt_ls") 
def search_o1_insert(
    q_ls: List[str],
    total_subq_list: List[List[str]], 
    total_final_info_list: List[List[str]],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

Search-O1 格式化插入 Prompt。

在 Prompt 中显式插入 `<|begin_search_query|>` 和搜索结果标记，构造完整的思维链上下文。

***

## EVisRAG & Multi-branch Prompts

### `gen_subq`

**签名**

```python theme={null}
@app.prompt(output="q_ls,ret_psg,gen_subq_template->prompt_ls")
def gen_subq(
    q_ls: List[str],
    ret_psg: List[str | Any],
    template: str | Path,
) -> List[PromptMessage]
```

**功能**

Loop/Branch Demo：基于文档生成子问题。

模板变量: `{{ question }}`, `{{ documents }}`

### `evisrag_vqa`

**签名**

```python theme={null}
@app.prompt(output="q_ls,ret_psg,evisrag_template->prompt_ls")
def evisrag_vqa(
    q_ls: List[str], 
    ret_psg: List[str | Any], 
    template: str | Path
) -> list[PromptMessage]
```

**功能**

多模态 VQA RAG Prompt。

根据检索到的图片数量，在 Prompt 中自动重复插入 `<image>` Token。

模板变量: `{{ question }}` (含自动注入的 image tokens)

***

## SurveyCPM Prompts

### `surveycpm_search`

**签名**

```python theme={null}
@app.prompt(output="instruction_ls,survey_ls,cursor_ls,surveycpm_search_template->prompt_ls")
def surveycpm_search(
    instruction_ls: List[str],
    survey_ls: List[str],
    cursor_ls: List[str | None],
    surveycpm_search_template: str | Path,
) -> List[PromptMessage]
```

**功能**

Survey Agent：决定下一步搜索内容。

解析 JSON 格式的大纲，生成当前大纲的文本描述。

模板变量: `{{ user_query }}`, `{{ current_outline }}`, `{{ current_instruction }}`

### `surveycpm_init_plan`

**签名**

```python theme={null}
@app.prompt(output="instruction_ls,retrieved_info_ls,surveycpm_init_plan_template->prompt_ls")
def surveycpm_init_plan(
    instruction_ls: List[str],
    retrieved_info_ls: List[str],
    surveycpm_init_plan_template: str | Path,
) -> List[PromptMessage]
```

**功能**

Survey Agent：初始化大纲规划。

模板变量: `{{ user_query }}`, `{{ current_information }}`

### `surveycpm_write`

**签名**

```python theme={null}
@app.prompt(output="instruction_ls,survey_ls,cursor_ls,retrieved_info_ls,surveycpm_write_template->prompt_ls")
def surveycpm_write(
    instruction_ls: List[str],
    survey_ls: List[str],
    cursor_ls: List[str | None],
    retrieved_info_ls: List[str],
    surveycpm_write_template: str | Path,
) -> List[PromptMessage]
```

**功能**

Survey Agent：撰写具体章节内容。

模板变量: `{{ user_query }}`, `{{ current_survey }}`, `{{ current_instruction }}`, `{{ current_information }}`

### `surveycpm_extend_plan`

**签名**

```python theme={null}
@app.prompt(output="instruction_ls,survey_ls,surveycpm_extend_plan_template->prompt_ls")
def surveycpm_extend_plan(
    instruction_ls: List[str],
    survey_ls: List[str],
    surveycpm_extend_plan_template: str | Path,
) -> List[PromptMessage]
```

**功能**

Survey Agent：扩展或修改大纲计划。

模板变量: `{{ user_query }}`, `{{ current_survey }}`

***

## 参数配置

```yaml servers/prompt/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# QA
template: prompt/qa_boxed.jinja

# RankCoT
kr_template: prompt/RankCoT_knowledge_refinement.jinja
qa_template: prompt/RankCoT_question_answering.jinja

# Search-R1
search_r1_gen_template: prompt/search_r1_append.jinja

# R1-Searcher
r1_searcher_gen_template: prompt/r1_searcher_append.jinja

# Search-o1
searcho1_reasoning_template: prompt/search_o1_reasoning.jinja
searcho1_refine_template: prompt/search_o1_refinement.jinja


# For other prompts, please add parameters here as needed

# Take webnote as an example:
webnote_gen_plan_template: prompt/webnote_gen_plan.jinja
webnote_init_page_template: prompt/webnote_init_page.jinja
webnote_gen_subq_template: prompt/webnote_gen_subq.jinja
webnote_fill_page_template: prompt/webnote_fill_page.jinja
webnote_gen_answer_template: prompt/webnote_gen_answer.jinja

# SurveyCPM
surveycpm_search_template: prompt/surveycpm_search.jinja
surveycpm_init_plan_template: prompt/surveycpm_init_plan.jinja
surveycpm_write_template: prompt/surveycpm_write.jinja
surveycpm_extend_plan_template: prompt/surveycpm_extend_plan.jinja
```

| 参数            | 说明                     |
| ------------- | ---------------------- |
| `template`    | 基础 QA 模板路径             |
| `kr_template` | RankCoT 知识精炼模板路径       |
| `qa_template` | RankCoT 问答模板路径         |
| `*_template`  | 对应各模块功能的 Jinja2 模板文件路径 |

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Generation

## `generation_init`

**签名**

```python theme={null}
def generation_init(
    backend_configs: Dict[str, Any],
    sampling_params: Dict[str, Any],
    extra_params: Optional[Dict[str, Any]] = None,
    backend: str = "vllm",
) -> None
```

**功能**

* 初始化推理后端与采样参数。
* 支持 `vllm`, `openai`, `hf` 三种后端。
* `extra_params` 可用于传递 `chat_template_kwargs` 或其他特定后端的参数。

***

## `generate`

**签名**

```python theme={null}
async def generate(
    prompt_ls: List[Union[str, Dict[str, Any]]],
    system_prompt: str = "",
) -> Dict[str, List[str]]
```

**功能**

* 纯文本对话生成。
* 自动处理列表中的 Prompt，支持字符串或 OpenAI 格式的字典。

**输出格式（JSON）**

```json theme={null}
{"ans_ls": ["answer for prompt_0", "answer for prompt_1", "..."]}
```

***

## `multimodal_generate`

**签名**

```python theme={null}
async def multimodal_generate(
    multimodal_path: List[List[str]],
    prompt_ls: List[Union[str, Dict[str, Any]]],
    system_prompt: str = "",
    image_tag: Optional[str] = None,
) -> Dict[str, List[str]]
```

**功能**

* 文图多模态对话生成。
* `multimodal_path`: 对应每个 Prompt 的图片路径列表（支持本地路径或 URL）。
* `image_tag`: 如果指定（如 `<img>`），则将图片插入到 Prompt 中该标签的位置；否则默认追加到 Prompt 末尾。

**输出格式（JSON）**

```json theme={null}
{"ans_ls": ["answer with images for prompt_0", "..."]}
```

***

## `multiturn_generate`

**签名**

```python theme={null}
async def multiturn_generate(
    messages: List[Dict[str, str]],
    system_prompt: str = "",
) -> Dict[str, List[str]]
```

**功能**

* 多轮对话生成。
* 仅支持单次调用的生成，不处理批量 Prompt。

**输出格式（JSON）**

```json theme={null}
{"ans_ls": ["assistant response"]}
```

***

## `vllm_shutdown`

**签名**

```python theme={null}
def vllm_shutdown() -> None
```

**功能**

* 显式关闭 vLLM 引擎并释放显存资源。
* 仅在使用 `vllm` 后端时有效。

***

## 参数配置

```yaml servers/generation/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# servers/generation/parameter.yaml
backend: vllm # options: vllm, openai
backend_configs:
  vllm:
    model_name_or_path: openbmb/MiniCPM4-8B
    gpu_ids: "2,3"
    gpu_memory_utilization: 0.9
    dtype: auto
    trust_remote_code: true
  openai:
    model_name: MiniCPM4-8B
    base_url: http://localhost:8000/v1
    api_key: "abc"
    concurrency: 8
    retries: 3
    base_delay: 1.0
  hf:
    model_name_or_path: openbmb/MiniCPM4-8B
    gpu_ids: '2,3'
    trust_remote_code: true
    batch_size: 8
sampling_params:
  temperature: 0.7
  top_p: 0.8
  max_tokens: 2048
extra_params:
  chat_template_kwargs:
    enable_thinking: false
system_prompt: ""
image_tag: null
```

参数说明：

| 参数                | 类型   | 说明                                             |
| ----------------- | ---- | ---------------------------------------------- |
| `backend`         | str  | 指定生成后端，可选 `vllm`、`openai` 或 `hf`（Transformers） |
| `backend_configs` | dict | 各后端模型及运行环境配置                                   |
| `sampling_params` | dict | 采样参数，用于控制生成多样性与长度                              |
| `extra_params`    | dict | 额外参数，如 `chat_template_kwargs`                  |
| `system_prompt`   | str  | 全局系统提示，将作为 `system` 消息加入上下文                    |
| `image_tag`       | str  | 图像占位符标签（如需）                                    |

`backend_configs` 详细说明：

| 后端         | 参数                       | 说明                        |
| ---------- | ------------------------ | ------------------------- |
| **vllm**   | `model_name_or_path`     | 模型名称或路径                   |
|            | `gpu_ids`                | 使用的 GPU ID（如 `"0,1"`）     |
|            | `gpu_memory_utilization` | GPU 显存占用比例（0–1）           |
|            | `dtype`                  | 数据类型（如 `auto`、`bfloat16`） |
|            | `trust_remote_code`      | 是否信任远程代码                  |
| **openai** | `model_name`             | OpenAI 模型名称或自建兼容模型        |
|            | `base_url`               | API 接口地址                  |
|            | `api_key`                | API 密钥                    |
|            | `concurrency`            | 最大并发请求数                   |
|            | `retries`                | API 重试次数                  |
|            | `base_delay`             | 每次重试基础等待时间（秒）             |
| **hf**     | `model_name_or_path`     | Transformers 模型路径         |
|            | `gpu_ids`                | GPU ID（同上）                |
|            | `trust_remote_code`      | 是否信任远程代码                  |
|            | `batch_size`             | 每次推理批量大小                  |

`sampling_params` 详细说明：

| 参数            | 类型    | 说明                  |
| ------------- | ----- | ------------------- |
| `temperature` | float | 控制随机性，越高生成越多样       |
| `top_p`       | float | nucleus sampling 阈值 |
| `max_tokens`  | int   | 生成最大词元数             |

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Evaluation

## `evaluate`

**签名**

```python theme={null}
@app.tool(output="pred_ls,gt_ls,metrics,save_path->eval_res")
def evaluate(
    pred_ls: List[str],
    gt_ls: List[List[str]],
    metrics: List[str] | None,
    save_path: str,
) -> Dict[str, Any]
```

**功能**

* 执行问答/生成类任务的自动指标评估。
* 支持指标：`acc`、`em`、`coverem`、`stringem`、`f1`、`rouge-1`、`rouge-2`、`rouge-l`。
* 结果自动保存为 `.json` 文件，并以 Markdown 表格形式打印。

***

## `evaluate_trec`

**签名**

```python theme={null}
@app.tool(output="run_path,qrels_path,ir_metrics,ks,save_path->eval_res")
def evaluate_trec(
    run_path: str,
    qrels_path: str,
    metrics: List[str] | None,
    ks: List[int] | None,
    save_path: str,
)
```

**功能**

* 基于 `pytrec_eval` 进行 IR 检索指标评估。
* 读取标准 TREC 格式：
  * **qrels**：`<qid> <iter> <docid> <rel>`
  * **run**：`<qid> Q0 <docid> <rank> <score> <tag>`
* 支持指标：`mrr`、`map`、`recall@k`、`precision@k`、`ndcg@k`。
* 自动统计聚合结果并以表格输出。

***

## `evaluate_trec_pvalue`

**签名**

```python theme={null}
@app.tool(
    output="run_new_path,run_old_path,qrels_path,ir_metrics,ks,n_resamples,save_path->eval_res"
)
def evaluate_trec_pvalue(
    run_new_path: str,
    run_old_path: str,
    qrels_path: str,
    metrics: List[str] | None,
    ks: List[int] | None,
    n_resamples: int | None,
    save_path: str,
)
```

**功能**

* 对两个 TREC 结果文件进行显著性比较，采用**双尾置换检验**计算 p-value。
* 默认重采样次数 `n_resamples=10000`。
* 输出均值、差异、p 值及显著性标识。

***

## 参数配置

```yaml servers/evaluation/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
save_path: output/evaluate_results.json

# QA task
metrics: [ 'acc', 'f1', 'em', 'coverem', 'stringem', 'rouge-1', 'rouge-2', 'rouge-l' ]

# Retrieval task
qrels_path: data/qrels.txt
run_path: data/run_a.txt
ks: [ 1, 5, 10, 20, 50, 100 ]
ir_metrics: [ "mrr", "map", "recall", "ndcg", "precision" ]

# significant
run_new_path: data/run_a.txt
run_old_path: data/run_b.txt
n_resamples: 10000
```

参数说明：

| 参数             | 类型         | 说明                                                      |
| -------------- | ---------- | ------------------------------------------------------- |
| `save_path`    | str        | 评估结果保存路径（将自动附带时间戳）                                      |
| `metrics`      | list\[str] | QA / 生成任务使用的指标集合                                        |
| `qrels_path`   | str        | TREC 格式真值文件路径                                           |
| `run_path`     | str        | 检索任务的结果文件                                               |
| `ks`           | list\[int] | 截断层级，用于计算 NDCG\@K、P\@K、Recall\@K 等                      |
| `ir_metrics`   | list\[str] | 检索任务指标名称，支持 `mrr`, `map`, `recall`, `ndcg`, `precision` |
| `run_new_path` | str        | 新模型生成的 run 文件路径（显著性分析）                                  |
| `run_old_path` | str        | 旧模型的 run 文件路径（显著性分析）                                    |
| `n_resamples`  | int        | 置换检验（Permutation Test）重采样次数                             |

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Router

## `route1` / `route2`

**签名**

```python theme={null}
@app.tool(output="query_list")
def route1(query_list: List[str]) -> Dict[str, List[Dict[str, str]]]
def route2(query_list: List[str]) -> Dict[str, List[Dict[str, str]]]
```

**功能**

* 基础路由示例。
* `route1`: 如果查询内容为 "1"，状态设为 "state1"，否则 "state2"。
* `route2`: 强制状态设为 "state2"。

***

## `ircot_check_end`

**签名**

```python theme={null}
@app.tool(output="ans_ls->ans_ls")
def ircot_check_end(ans_ls: List[str]) -> Dict[str, List[Dict[str, str]]]
```

**功能**

* IRCoT 流程检查。
* 检查回答中是否包含 `"so the answer is"`（忽略大小写）。
* 包含则标记状态为 `"complete"`，否则为 `"incomplete"`。

***

## `search_r1_check`

**签名**

```python theme={null}
@app.tool(output="ans_ls->ans_ls")
def search_r1_check(ans_ls: List[str]) -> Dict[str, List[Dict[str, str]]]
```

**功能**

* 检查 Search-R1 生成是否结束。
* 依据：文本中包含 `<|endoftext|>` 或 `<|im_end|>`。
* 满足条件标记为 `"complete"`，否则 `"incomplete"`。

***

## `webnote_check_page`

**签名**

```python theme={null}
@app.tool(output="page_ls->page_ls")
def webnote_check_page(page_ls: List[str]) -> Dict[str, List[Dict[str, str]]]
```

**功能**

* WebNote 流程检查。
* 若页面内容包含 `"to be filled"`（忽略大小写），标记为 `"incomplete"`，否则 `"complete"`。

***

## `r1_searcher_check`

**签名**

```python theme={null}
@app.tool(output="ans_ls->ans_ls")
def r1_searcher_check(ans_ls: List[str]) -> Dict[str, List[Dict[str, str]]]
```

**功能**

* 检查 R1-Searcher 生成是否结束。
* 依据：文本中包含 `<|endoftext|>`、`<|im_end|>` 或 `</answer>`。
* 满足条件标记为 `"complete"`，否则 `"incomplete"`。

***

## `search_o1_check`

**签名**

```python theme={null}
@app.tool(output="ans_ls,q_ls,total_subq_list,total_reason_list,total_final_info_list->ans_ls,q_ls,total_subq_list,total_reason_list,total_final_info_list")
def search_o1_check(
    ans_ls: List[str],
    q_ls: List[str],
    total_subq_list: List[List[Any]],
    total_reason_list: List[List[Any]],
    total_final_info_list: List[List[Any]],
) -> Dict[str, List[Dict[str, Any]]]
```

**功能**

* Search-o1 流程状态检查。
* 检查回答中的特殊标记：
  * 若包含 `<|end_search_query|>`：状态设为 `"retrieve"`（继续检索）。
  * 若包含 `<|im_end|>` 或其他情况：状态设为 `"stop"`（停止检索，输出答案）。
* 将所有关联列表（`q_ls`, `subq`, `reason`, `info`）同步更新状态。

***

## `check_model_state`

**签名**

```python theme={null}
@app.tool(output="ans_ls->ans_ls")
def check_model_state(ans_ls: List[str]) -> Dict[str, List[Dict[str, str]]]
```

**功能**

* 通用模型状态检查。
* 若回答中包含 `<search>` 标签，标记状态为 `"continue"`，否则 `"stop"`。

***

## `surveycpm_state_router`

**签名**

```python theme={null}
@app.tool(output="state_ls,cursor_ls,survey_ls,step_ls,extend_time_ls,extend_result_ls->state_ls,cursor_ls,survey_ls,step_ls,extend_time_ls,extend_result_ls")
def surveycpm_state_router(
    state_ls: List[str],
    cursor_ls: List[str | None],
    survey_ls: List[str],
    step_ls: List[int],
    extend_time_ls: List[int],
    extend_result_ls: List[str],
) -> Dict[str, List[Dict[str, Any]]]
```

**功能**

* SurveyCPM 专用路由。
* 这是一个 Pass-through 工具，它将所有输入的列表元素（状态、光标、大纲等）打包成带有 `"state"` 字段的字典。
* 目的：使 UltraRAG 框架能够根据 `state` 字段自动分发数据到对应的 Pipeline 分支。

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Custom

## Search-R1 Tools

### `search_r1_query_extract`

```python theme={null}
@app.tool(output="ans_ls->extract_query_list")
def search_r1_query_extract(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：从模型回答中提取查询内容。
* **逻辑**：使用正则 `r"<search>([^<]*)"` 提取最后一个 `<search>` 标签内的内容。如果未找到，返回 "There is no query."；如果查询未以 `?` 结尾，自动补全。

### `r1_searcher_query_extract`

```python theme={null}
@app.tool(output="ans_ls->extract_query_list")
def r1_searcher_query_extract(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：从 R1-Searcher 回答中提取查询。
* **逻辑**：使用正则 `r"<|begin_of_query|>([^<]*)"` 提取最后一个标签内容。

***

## IRCoT & IterRetGen Tools

### `iterretgen_nextquery`

```python theme={null}
@app.tool(output="q_ls,ret_psg->nextq_ls")
def iterretgen_nextquery(q_ls: List[str], ans_ls: List[str | Any]) -> Dict[str, List[str]]
```

* **功能**：迭代检索生成。
* **逻辑**：`next_query = f"{q} {ans}"`。将原始问题与生成的回答拼接作为下一次检索的 Query。

### `ircot_get_first_sent`

```python theme={null}
@app.tool(output="ans_ls->q_ls")
def ircot_get_first_sent(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：提取回答的第一句话（至句号或问号/感叹号结束）。

### `ircot_extract_ans`

```python theme={null}
@app.tool(output="ans_ls->pred_ls")
def ircot_extract_ans(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：提取最终答案。
* **逻辑**：匹配 `so the answer is [...]` 后的内容。

***

## Search-o1 Tools

### `search_o1_init_list`

```python theme={null}
@app.tool(output="q_ls->total_subq_list,total_reason_list,total_final_info_list")
def search_o1_init_list(q_ls: List[str]) -> Dict[str, List[Any]]
```

* **功能**：初始化 Search-o1 所需的累加列表（子问题、推理、最终信息），初始填充 `<PAD>`。

### `search_o1_combine_list`

```python theme={null}
@app.tool(output="total_subq_list, extract_query_list, total_reason_list, extract_reason_list->total_subq_list, total_reason_list")
def search_o1_combine_list(...)
```

* **功能**：将当前步骤提取的 Query 和 Reasoning 追加到总列表中。

### `search_o1_query_extract`

```python theme={null}
@app.tool(output="ans_ls->extract_query_list")
def search_o1_query_extract(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：提取 `<|begin_search_query|>...<|end_search_query|>` 之间的内容。

### `search_o1_reasoning_extract`

```python theme={null}
@app.tool(output="ans_ls->extract_reason_list")
def search_o1_reasoning_extract(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：提取 `<|begin_search_query|>` 之前的所有文本作为推理过程。

### `search_o1_extract_final_information`

```python theme={null}
@app.tool(output="ans_ls->extract_final_infor_list")
def search_o1_extract_final_information(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：提取 `**Final Information**` 标记之后的内容。

***

## Utility Tools

### `output_extract_from_boxed`

```python theme={null}
@app.tool(output="ans_ls->pred_ls")
def output_extract_from_boxed(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：从 LaTeX `\boxed{...}` 中提取答案。支持嵌套括号处理和格式清理。

### `merge_passages`

```python theme={null}
@app.tool(output="temp_psg,ret_psg->ret_psg")
def merge_passages(temp_psg: List[str | Any], ret_psg: List[str | Any]) -> Dict[str, List[str | Any]]
```

* **功能**：将 `temp_psg` 列表追加到 `ret_psg` 列表中。

### `evisrag_output_extract_from_special`

```python theme={null}
@app.tool(output="ans_ls->pred_ls")
def evisrag_output_extract_from_special(ans_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：从 `<answer>...</answer>` 标签提取答案。

### `assign_citation_ids` / `assign_citation_ids_stateful`

* `assign_citation_ids`: 为检索到的段落分配 `[1]`, `[2]` 形式的引用 ID。
* `assign_citation_ids_stateful`: 使用 `CitationRegistry` 类维护全局引用 ID（跨步骤去重）。
* `init_citation_registry`: 重置全局引用注册表。

***

## SurveyCPM Tools

### `surveycpm_state_init`

```python theme={null}
@app.tool(output="instruction_ls->state_ls,cursor_ls,survey_ls,step_ls,extend_time_ls,extend_result_ls,retrieved_info_ls,parsed_ls")
def surveycpm_state_init(instruction_ls: List[str]) -> Dict[str, List]
```

* **功能**：初始化 SurveyCPM 状态机。
* **初始状态**：`state="search"`, `cursor="outline"`, `step=0`。

### `surveycpm_parse_search_response`

```python theme={null}
@app.tool(output="response_ls,surveycpm_hard_mode->keywords_ls,parsed_ls")
def surveycpm_parse_search_response(response_ls: List[str], surveycpm_hard_mode: bool = True) -> Dict[str, List]
```

* **功能**：解析模型生成的搜索指令（JSON 或 XML 格式），提取关键词列表。

### `surveycpm_process_passages`

```python theme={null}
@app.tool(output="ret_psg_ls->retrieved_info_ls")
def surveycpm_process_passages(ret_psg_ls: List[List[List[str]]]) -> Dict[str, List[str]]
```

* **功能**：处理检索段落，去重并限制数量（Top-K），拼接为字符串。

### `surveycpm_after_init_plan` / `after_write` / `after_extend`

* **功能**：解析 Agent 对不同阶段（初始化大纲、撰写内容、扩展计划）的响应。
* **逻辑**：
  * 调用 `surveycpm_parse_response` 验证格式和内容。
  * 成功则更新 `survey_ls`（大纲结构）和 `cursor_ls`（当前光标位置）。
  * 失败则保留原状态以便重试。

### `surveycpm_update_state`

```python theme={null}
@app.tool(output="state_ls,cursor_ls,extend_time_ls,extend_result_ls,step_ls,parsed_ls,surveycpm_max_step,surveycpm_max_extend_step->state_ls,extend_time_ls,step_ls")
def surveycpm_update_state(...)
```

* **功能**：核心状态机逻辑。
* **状态转移**：
  * `search` -> `analyst-init_plan` (cursor="outline")
  * `search` -> `write` (cursor=section-X)
  * `write` -> `search` (继续写) 或 `analyst-extend_plan` (写完当前部分)
  * `analyst-extend_plan` -> `search` (扩展成功) 或 `done` (无扩展)
  * 超出最大步数 -> `done`

### `surveycpm_format_output`

```python theme={null}
@app.tool(output="survey_ls,instruction_ls->ans_ls")
def surveycpm_format_output(survey_ls: List[str], instruction_ls: List[str]) -> Dict[str, List[str]]
```

* **功能**：将最终的 Survey JSON 转换为 Markdown 格式。
* **处理**：自动处理标题层级（# ## ###）、引用格式化（`\cite{...}` 转 `[1]`）和文本清理。

***

## 参数配置

```yaml servers/custom/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
surveycpm_hard_mode: false
surveycpm_max_step: 140
surveycpm_max_extend_step: 12
```

| 参数                          | 类型   | 说明                                    |
| --------------------------- | ---- | ------------------------------------- |
| `surveycpm_hard_mode`       | bool | 是否启用 SurveyCPM 的严格解析模式（验证 JSON 字段完整性） |
| `surveycpm_max_step`        | int  | 最大总执行步数，超过强制结束                        |
| `surveycpm_max_extend_step` | int  | 最大扩展计划次数                              |
