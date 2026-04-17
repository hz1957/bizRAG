> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# 模块概述

## Server 简介

在典型的 RAG 系统中，整体流程通常由多个功能模块组成，例如检索器（Retriever）、生成器（Generator）等。这些模块分别承担不同的任务，并通过流程编排协同工作，从而完成复杂的问答与推理过程。

在 UltraRAG 中，我们基于 MCP（Model Context Protocol） 架构，对这些功能模块进行了统一封装，提出了更加标准化的实现方式——Server。

<Note>Server 本质上就是一个具备独立功能的 RAG 模块组件。</Note>

每个 Server 封装一类核心任务逻辑（如检索、生成、评测等），并通过函数级别的 Tool 对外提供标准化接口。借助这一机制，Server 可以在完整的 Pipeline 中被灵活组合、调用与复用，从而实现模块化、可扩展的系统构建方式。

## Server开发

为了帮助你更好地理解 Server 的使用方式，本节将通过一个简易示例，演示从零构建一个自定义 Server 的完整开发流程。

### Step1：创建Server文件

首先，在`servers`文件夹下新建名为`sayhello`的文件夹，并在其中创建源码目录`sayhello/src`。然后，在 `src` 目录下新建文件 `sayhello.py`，作为 Server 的主程序入口。

在 UltraRAG 中，所有 Server 都通过基类 `UltraRAG_MCP_Server` 完成实例化。示例如下：

```python servers/sayhello/src/sayhello.py icon="python" theme={null}
from ultrarag.server import UltraRAG_MCP_Server

app = UltraRAG_MCP_Server("sayhello")

if __name__ == "__main__":
    # Start the sayhello server using stdio transport
    app.run(transport="stdio")
```

### Step2：实现工具函数（Tool）

使用 `@app.tool` 装饰器即可注册工具函数（Tool）。这些函数将在 Pipeline 执行过程中被调用，用于实现具体的功能逻辑。

例如，下面的示例定义了一个最简单的问候函数 `greet`，输入一个名字，返回相应的问候语：

```python servers/sayhello/src/sayhello.py icon="python" theme={null}
from typing import Dict
from ultrarag.server import UltraRAG_MCP_Server

app = UltraRAG_MCP_Server("sayhello")

@app.tool(output="name->msg")
def greet(name: str) -> Dict[str, str]:
    ret = f"Hello, {name}!"
    app.logger.info(ret)
    return {"msg": ret}

if __name__ == "__main__":
    # Start the sayhello server using stdio transport
    app.run(transport="stdio")

```

### Step3：配置参数文件

接下来，在 `sayhello` 文件夹下创建参数配置文件 `parameter.yaml`。该文件用于声明工具（Tool）所需的输入参数及其默认值，方便在 Pipeline 运行时自动加载与传递。

示例如下：

```yaml servers/sayhello/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
name: UltraRAG v3
```

此处定义了参数 name，其默认值为 "UltraRAG v3"。

### 参数注册机制

<Note>若不同 Prompt Tool 存在参数命名冲突，请参考 [Prompt Server](/pages/cn/rag_servers/prompt) 中的“多 Prompt Tool 调用场景”部分了解解决方案。</Note>

UltraRAG 在 build 阶段会自动读取每个 Server 目录下的 `parameter.yaml` 文件，并据此感知并注册工具函数所需的参数。在使用时需注意以下几点：

* 参数共享机制：当多个 Tool 需要共用同一个参数（如 template、model\_name\_or\_path 等），可在 `parameter.yaml` 中仅声明一次并复用，无需重复定义。
* 字段覆盖风险：若多个 Tool 所需参数的名称相同但含义或默认值不同，应显式区分字段名，使用不同的名称，以避免在自动生成的配置文件中被覆盖。
* 上下文自动推断机制：若工具函数中的某些输入参数未出现在 ·parameter.yaml· 中，UltraRAG 会默认尝试从运行时上下文中推断（即从上游 Tool 的输出中获取）。因此，仅需在参数无法通过上下文自动传递时，才需要在 `parameter.yaml` 中显式定义。

### 基于类封装共享变量

在某些场景下，我们可能希望在同一个 Server 内部维护共享状态或变量，例如模型实例、缓存对象、配置等。此时，可以将 Server 封装为一个类，并在类的初始化阶段完成共享变量的定义与 Tool 的注册。

以下示例展示了如何将 sayhello Server 封装为类，以实现内部变量共享：

```python servers/sayhello/src/sayhello.py icon="python" highlight="9" theme={null}
from typing import Dict
from ultrarag.server import UltraRAG_MCP_Server

app = UltraRAG_MCP_Server("sayhello")

class Sayhello:
    def __init__(self, mcp_inst: UltraRAG_MCP_Server):
        mcp_inst.tool(self.greet, output="name->msg")
        self.sen = "Nice to meet you"

    def greet(self, name: str) -> Dict[str, str]:
        ret = f"Hello, {name}! {self.sen}!"
        app.logger.info(ret)
        return {"msg": ret}

if __name__ == "__main__":
    Sayhello(app)
    app.run(transport="stdio")
```

在此示例中，`self.sen` 用于模拟需要在不同 `Tool` 之间共享的变量。这种方式特别适用于需要加载模型、重复配置参数的场景。

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Corpus

## 作用

Corpus Server 是 UltraRAG 中用于处理原始语料文档的核心组件。它支持从多种数据源中解析、提取并标准化文本或图像内容，并提供多种切块策略，将原始文档转换为可直接用于后续检索与生成的格式。

Corpus Server 的主要功能包括：

* 文档解析：支持多种文件类型（如 .pdf、.txt、.md、.docx等）的内容提取。
* 语料构建：将解析后的内容保存为标准化的 .jsonl 结构，每行对应一个独立文档。
* 图像转换：支持将 PDF 页面转换为图像语料，保留版面与视觉结构信息。
* 文本切块：提供 Token、Sentence、Recursive等多种切分策略。

示例数据：

文本模态：

```json data/corpus_example.jsonl icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": "2066692", "contents": "Truman Sports Complex The Harry S. Truman Sports...."}
{"id": "15106858", "contents": "Arrowhead Stadium 1970s...."}
```

图像模态：

```json icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": 0, "image_id": "UltraRAG/page_0.jpg", "image_path": "image/UltraRAG/page_0.jpg"}
{"id": 1, "image_id": "UltraRAG/page_1.jpg", "image_path": "image/UltraRAG/page_1.jpg"}
{"id": 2, "image_id": "UltraRAG/page_2.jpg", "image_path": "image/UltraRAG/page_2.jpg"}
```

## 文档解析示例

### 文本解析

Corpus Server 支持多种文本解析格式，包括 `.pdf、.txt、.md、.docx、.xps、.oxps、.epub、.mobi、.fb2` 等。

```yaml examples/build_text_corpus.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  corpus: servers/corpus

# MCP Client Pipeline
pipeline:
- corpus.build_text_corpus
```

编译 Pipeline：

```shell theme={null}
ultrarag build examples/build_text_corpus.yaml
```

根据实际情况修改相应字段：

```yaml examples/parameters/build_text_corpus_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
corpus:
  parse_file_path: data/UltraRAG.pdf
  text_corpus_save_path: corpora/text.jsonl
```

其中`parse_file_path` 可以是单个文件，也可以是文件夹路径——当指定为文件夹时，系统会自动遍历其中所有可解析文件并批量读取。

运行 Pipeline：

```shell theme={null}
ultrarag run examples/build_text_corpus.yaml
```

执行成功后，系统会自动解析文本并输出标准化语料文件，示例如下：

```json icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": "UltraRAG", "title": "UltraRAG", "contents": "xxxxx"}
```

### PDF转图像

在多模态 RAG 场景中，[一类方法](https://arxiv.org/abs/2410.10594)是将文档页面直接转换为图像，并以完整图像形式进行检索与生成。
这种方式的优势在于能够保留文档的排版、格式与视觉结构，从而使检索和理解更贴近真实阅读场景。

```yaml examples/build_image_corpus.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  corpus: servers/corpus

# MCP Client Pipeline
pipeline:
- corpus.build_image_corpus
```

编译 Pipeline：

```shell theme={null}
ultrarag build examples/build_image_corpus.yaml
```

根据实际情况修改相应字段：

```yaml examples/parameters/build_image_corpus_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
corpus:
  image_corpus_save_path: corpora/image.jsonl
  parse_file_path: data/UltraRAG.pdf
```

同样地，`parse_file_path` 参数既可指定为单个文件，也可为文件夹路径。当设置为文件夹时，系统会自动遍历并处理其中的所有文件。

运行 Pipeline：

```shell theme={null}
ultrarag run examples/build_image_corpus.yaml
```

执行成功后，系统将保存生成的图像语料文件，每条记录包含图像标识符与相对路径，生成的 .jsonl 文件可直接作为多模态检索或生成任务的输入。输出示例如下：

```json icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": 0, "image_id": "UltraRAG/page_0.jpg", "image_path": "image/UltraRAG/page_0.jpg"}
{"id": 1, "image_id": "UltraRAG/page_1.jpg", "image_path": "image/UltraRAG/page_1.jpg"}
{"id": 2, "image_id": "UltraRAG/page_2.jpg", "image_path": "image/UltraRAG/page_2.jpg"}
```

### MinerU解析

[MinerU](https://github.com/opendatalab/MinerU) 是业界广受好评的 PDF 解析框架，支持高精度的文本与版面结构提取。
UltraRAG 将 MinerU 无缝集成为内置工具，可直接在 Pipeline 中调用，实现一站式的 PDF → 文本 + 图像 语料构建。

```yaml examples/build_mineru_corpus.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  corpus: servers/corpus

# MCP Client Pipeline
pipeline:
- corpus.mineru_parse
- corpus.build_mineru_corpus
```

编译 Pipeline：

```shell theme={null}
ultrarag build examples/build_mineru_corpus.yaml
```

根据实际情况修改相应字段：

```yaml examples/parameters/build_mineru_corpus_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
corpus:
  image_corpus_save_path: corpora/image.jsonl    # 图像语料保存路径
  mineru_dir: corpora/                           # MinerU 解析结果保存目录
  mineru_extra_params:
    source: modelscope                           # 模型下载源（默认为 Hugging Face，可选 modelscope）
  parse_file_path: data/UltraRAG.pdf             # 要解析的文件或文件夹路径
  text_corpus_save_path: corpora/text.jsonl      # 文本语料保存路径
```

同样地，`parse_file_path` 参数既可为单个文件，也可为文件夹路径。

运行 Pipeline（首次执行时需下载 MinerU 模型，速度较慢）：

```shell theme={null}
ultrarag run examples/build_mineru_corpus.yaml
```

执行成功后，系统将自动输出对应的 文本语料 与 图像语料 文件，其格式与 `build_text_corpus` 和 `build_image_corpus` 一致，可直接用于多模态检索与生成任务。

## 文档切块示例

UltraRAG 集成了 [chonkie](https://docs.chonkie.ai/common/welcome) 文档切块库，并内置三种主流切块策略：`Token Chunker`，`Sentence Chunker`以及`Recursive Chunker`，可灵活应对不同类型的文本结构。

* `Token Chunker`：按分词器、单词或字符进行分块，适用于一般文本。
* `Sentence Chunker`：按句子边界切分，保证语义完整性。
* `Recursive Chunker`：适用于结构良好的长文档（如书籍、论文），能自动按层级划分内容。

```yaml examples/corpus_chunk.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  corpus: servers/corpus

# MCP Client Pipeline
pipeline:
- corpus.chunk_documents
```

编译 Pipeline：

```shell theme={null}
ultrarag build examples/corpus_chunk.yaml
```

根据实际情况修改相应字段：

```yaml examples/parameters/corpus_chunk_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b"                       # 是否将标题附加到每个 chunk 开头 theme={null}
corpus:
  chunk_backend: token    # 切块策略，可选 token / sentence / recursive
  chunk_backend_configs:
    recursive:
      min_characters_per_chunk: 12  # 每块最小长度，防止过短
    sentence:
      chunk_overlap: 50              # 相邻块重叠字符数
      delim: '[''.'', ''!'', ''?'', ''\n'']'  # 句子分隔符
      min_sentences_per_chunk: 1  # 每块最少句子数
    token:
      chunk_overlap: 50             # 相邻块重叠 token 数
  chunk_path: corpora/chunks.jsonl      # 输出切块后语料的保存路径
  chunk_size: 256                      # 每块最大 token 数
  raw_chunk_path: corpora/text.jsonl    # 原始文本语料路径
  tokenizer_or_token_counter: character # 使用的分词器
  use_title: false                     # 是否将标题附加到每个 chunk 开头
```

运行 Pipeline：

```shell theme={null}
ultrarag run examples/corpus_chunk.yaml
```

执行完成后，系统将输出标准化的切块语料文件，可直接用于后续检索与生成模块。
输出示例如下：

```json icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": 0, "doc_id": "UltraRAG", "title": "UltraRAG", "contents": "xxxxx"}
{"id": 1, "doc_id": "UltraRAG", "title": "UltraRAG", "contents": "xxxxx"}
{"id": 2, "doc_id": "UltraRAG", "title": "UltraRAG", "contents": "xxxxx"}
```

<Note>你可以在同一 Pipeline 中同时调用解析工具与切块工具，以构建属于你自己的个性化知识库。</Note>

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Benchmark

## 作用

Benchmark Server 用于加载评测数据集，常用于基准测试、问答任务或生成任务中的数据配置阶段。

<Info>我们强烈推荐将数据预处理为`.jsonl`格式。</Info>

示例数据：

```json data/sample_nq_10.jsonl icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": 0, "question": "when was the last time anyone was on the moon", "golden_answers": ["14 December 1972 UTC", "December 1972"], "meta_data": {}}
{"id": 1, "question": "who wrote he ain't heavy he's my brother lyrics", "golden_answers": ["Bobby Scott", "Bob Russell"], "meta_data": {}}
{"id": 2, "question": "how many seasons of the bastard executioner are there", "golden_answers": ["one", "one season"], "meta_data": {}}
{"id": 3, "question": "when did the eagles win last super bowl", "golden_answers": ["2017"], "meta_data": {}}
{"id": 4, "question": "who won last year's ncaa women's basketball", "golden_answers": ["South Carolina"], "meta_data": {}}
```

## 使用示例

### 基本用法

```yaml examples/load_data.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark

# MCP Client Pipeline
pipeline:
- benchmark.get_data
```

运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build examples/load_data.yaml
```

根据实际情况修改相应字段：

```yaml examples/parameters/load_data_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
    limit: -1
    name: nq
    path: data/sample_nq_10.jsonl
    seed: 42
    shuffle: false
```

运行以下命令执行该 Pipeline：

```shell theme={null}
ultrarag run examples/load_data.yaml
```

运行完成后，系统将自动加载并输出数据样本信息，为后续的检索与生成任务提供输入支持。

### 新增加载数据集字段

在某些情况下，我们可能不仅需要加载 `query` 与 `ground_truth` 字段，还希望使用数据集中的其他信息，如已检索的 `passage`。
此时，可以通过修改 Benchmark Server 的代码，新增需要返回的字段。

<Note>你可以用相同方式扩展其他字段（例如 cot、retrieved\_passages 等），只需在装饰器输出与 key\_map 中同步添加对应键名即可。</Note>
<Check>如果你有生成好的结果（如 pred 字段），可以配合 [Evaluation Server](/pages/cn/rag_servers/evaluation) 一同使用，实现快速评估。</Check>

以下示例演示如何在 `get_data` 函数中新增 `id_ls` 字段：

```python servers/prompt/src/benchmark.py icon="python" theme={null}
@app.tool(output="benchmark->q_ls,gt_ls") # [!code --]
@app.tool(output="benchmark->q_ls,gt_ls,id_ls") # [!code ++]
def get_data(
    benchmark: Dict[str, Any],
) -> Dict[str, List[Any]]:
```

然后，运行以下命令重新编译 Pipeline：

```shell theme={null}
ultrarag build examples/load_data.yaml
```

在生成的参数文件中，添加字段 `id_ls` 并指定其在原始数据中的对应键名：

```yaml examples/parameters/load_data_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
      id_ls: id  # [!code ++]
    limit: -1
    name: nq
    path: data/sample_nq_10.jsonl
    seed: 42
    shuffle: false
```

完成修改后，重新运行 Pipeline 即可加载包含 id 的数据样本。

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Benchmark

## 作用

Benchmark Server 用于加载评测数据集，常用于基准测试、问答任务或生成任务中的数据配置阶段。

<Info>我们强烈推荐将数据预处理为`.jsonl`格式。</Info>

示例数据：

```json data/sample_nq_10.jsonl icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": 0, "question": "when was the last time anyone was on the moon", "golden_answers": ["14 December 1972 UTC", "December 1972"], "meta_data": {}}
{"id": 1, "question": "who wrote he ain't heavy he's my brother lyrics", "golden_answers": ["Bobby Scott", "Bob Russell"], "meta_data": {}}
{"id": 2, "question": "how many seasons of the bastard executioner are there", "golden_answers": ["one", "one season"], "meta_data": {}}
{"id": 3, "question": "when did the eagles win last super bowl", "golden_answers": ["2017"], "meta_data": {}}
{"id": 4, "question": "who won last year's ncaa women's basketball", "golden_answers": ["South Carolina"], "meta_data": {}}
```

## 使用示例

### 基本用法

```yaml examples/load_data.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark

# MCP Client Pipeline
pipeline:
- benchmark.get_data
```

运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build examples/load_data.yaml
```

根据实际情况修改相应字段：

```yaml examples/parameters/load_data_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
    limit: -1
    name: nq
    path: data/sample_nq_10.jsonl
    seed: 42
    shuffle: false
```

运行以下命令执行该 Pipeline：

```shell theme={null}
ultrarag run examples/load_data.yaml
```

运行完成后，系统将自动加载并输出数据样本信息，为后续的检索与生成任务提供输入支持。

### 新增加载数据集字段

在某些情况下，我们可能不仅需要加载 `query` 与 `ground_truth` 字段，还希望使用数据集中的其他信息，如已检索的 `passage`。
此时，可以通过修改 Benchmark Server 的代码，新增需要返回的字段。

<Note>你可以用相同方式扩展其他字段（例如 cot、retrieved\_passages 等），只需在装饰器输出与 key\_map 中同步添加对应键名即可。</Note>
<Check>如果你有生成好的结果（如 pred 字段），可以配合 [Evaluation Server](/pages/cn/rag_servers/evaluation) 一同使用，实现快速评估。</Check>

以下示例演示如何在 `get_data` 函数中新增 `id_ls` 字段：

```python servers/prompt/src/benchmark.py icon="python" theme={null}
@app.tool(output="benchmark->q_ls,gt_ls") # [!code --]
@app.tool(output="benchmark->q_ls,gt_ls,id_ls") # [!code ++]
def get_data(
    benchmark: Dict[str, Any],
) -> Dict[str, List[Any]]:
```

然后，运行以下命令重新编译 Pipeline：

```shell theme={null}
ultrarag build examples/load_data.yaml
```

在生成的参数文件中，添加字段 `id_ls` 并指定其在原始数据中的对应键名：

```yaml examples/parameters/load_data_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
      id_ls: id  # [!code ++]
    limit: -1
    name: nq
    path: data/sample_nq_10.jsonl
    seed: 42
    shuffle: false
```

完成修改后，重新运行 Pipeline 即可加载包含 id 的数据样本。

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Reranker

## 作用

Reranker Server 是 UltraRAG 中用于 对检索结果进行精排的模块。
它接收来自 Retriever Server 的初步检索结果，并基于语义相关性对候选文档进行重新排序，
从而提升检索阶段的精度与最终生成结果的质量。
该模块原生支持多种主流后端包括 [Sentence-Transformers](https://github.com/UKPLab/sentence-transformers)、
[Infinity](https://github.com/michaelfeil/infinity) 以及 [OpenAI](https://platform.openai.com/docs/guides/embeddings)。

## 使用示例

```yaml examples/corpus_rerank.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="5,14,15" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark
  retriever: servers/retriever
  reranker: servers/reranker

# MCP Client Pipeline
pipeline:
- benchmark.get_data
- retriever.retriever_init
- retriever.retriever_embed
- retriever.retriever_index
- retriever.retriever_search
- reranker.reranker_init
- reranker.reranker_rerank
```

运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build examples/corpus_rerank.yaml
```

修改参数：

```yaml examples/parameters/corpus_search_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
    limit: -1
    name: nq
    path: data/sample_nq_10.jsonl
    seed: 42
    shuffle: false
reranker:
  backend: sentence_transformers
  backend_configs:
    infinity:
      bettertransformer: false
      device: cuda
      model_warmup: false
      pooling_method: auto
      trust_remote_code: true
    openai:
      api_key: ''
      base_url: https://api.openai.com/v1
      model_name: text-embedding-3-small
    sentence_transformers:
      device: cuda
      trust_remote_code: true
  batch_size: 16
  gpu_ids: 0
  model_name_or_path: openbmb/MiniCPM-Reranker-Light # [!code --]
  model_name_or_path: BAAI/bge-reranker-large # [!code ++]
  query_instruction: ''
  top_k: 5
retriever:
  backend: sentence_transformers
  backend_configs:
    bm25:
      lang: en
      save_path: index/bm25
    infinity:
      bettertransformer: false
      model_warmup: false
      pooling_method: auto
      trust_remote_code: true
    openai:
      api_key: abc
      base_url: https://api.openai.com/v1
      model_name: text-embedding-3-small
    sentence_transformers:
      sentence_transformers_encode:
        encode_chunk_size: 256
        normalize_embeddings: false
        psg_prompt_name: document
        psg_task: null
        q_prompt_name: query
        q_task: null
      trust_remote_code: true
  batch_size: 16
  collection_name: wiki
  corpus_path: data/corpus_example.jsonl
  embedding_path: embedding/embedding.npy
  gpu_ids: 0,1 # [!code --]
  gpu_ids: 1 # [!code ++]
  index_backend: faiss
  index_backend_configs:
    faiss:
      index_chunk_size: 10000
      index_path: index/index.index
      index_use_gpu: true
    milvus:
      id_field_name: id
      id_max_length: 64
      index_chunk_size: 1000
      index_params:
        index_type: AUTOINDEX
        metric_type: IP
      metric_type: IP
      search_params:
        metric_type: IP
        params: {}
      text_field_name: contents
      text_max_length: 60000
      token: null
      uri: index/milvus_demo.db
      vector_field_name: vector
  is_demo: false
  is_multimodal: false
  model_name_or_path: openbmb/MiniCPM-Embedding-Light # [!code --]
  model_name_or_path: Qwen/Qwen3-Embedding-0.6B # [!code ++]
  overwrite: false
  query_instruction: ''
  top_k: 5
```

运行 Pipeline：

```shell theme={null}
ultrarag run examples/corpus_rerank.yaml
```

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Prompt

## 作用

Prompt Tool 是用于构建语言模型输入（Prompt）的核心组件。
每个 Prompt Tool 由 `@app.prompt` 装饰器定义，其主要职责是：
根据输入内容（如问题、检索到的段落等），加载对应的模板文件，并生成标准化的 PromptMessage，
以便直接传递给大语言模型（LLM）进行生成或推理。

## 实现示例

### Step 1：准备 Prompt 模板

请将你的 prompt 模板保存为 `.jinja` 结尾的文件，例如：

```jinja prompt/qa_rag_boxed.jinja icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/jinja.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=a15fd18398a4c6c7fac44f02ba3dbecc" theme={null}
Please answer the following question based on the given documents.
Think step by step.
Provide your final answer in the format \boxed{YOUR_ANSWER}.

Documents:
{{documents}}

Question: {{question}}
```

### Step 2：在 Prompt Server 中实现 Tool

调用 `load_prompt_template` 方法加载模板，并在 Prompt Server 中实现一个工具函数用于组装 prompt：

```python servers/prompt/src/prompt.py icon="python" theme={null}
@app.prompt(output="q_ls,ret_psg,template->prompt_ls")
def qa_rag_boxed(
    q_ls: List[str], ret_psg: List[str | Any], template: str | Path
) -> list[PromptMessage]:
    template: Template = load_prompt_template(template)
    ret = []
    for q, psg in zip(q_ls, ret_psg):
        passage_text = "\n".join(psg)
        p = template.render(question=q, documents=passage_text)
        ret.append(p)
    return ret
```

## 调用示例

在调用模型生成工具前，需要先通过对应的 Prompt Tool 构建输入提示。

```yaml examples/rag_full.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="3,16" theme={null}
servers:
  benchmark: servers/benchmark
  retriever: servers/retriever
  prompt: servers/prompt
  generation: servers/generation
  evaluation: servers/evaluation
  custom: servers/custom

pipeline:
- benchmark.get_data
- retriever.retriever_init
- retriever.retriever_embed
- retriever.retriever_index
- retriever.retriever_search
- generation.generation_init
- prompt.qa_rag_boxed
- generation.generate
- custom.output_extract_from_boxed
- evaluation.evaluate
```

## 多 Prompt Tool 调用场景

在一些复杂的 Pipeline 中，模型往往需要在不同阶段执行不同任务——例如，先生成子问题，再根据新的检索结果生成最终答案。
此时，就需要在同一 Pipeline 中配置多个 Prompt Tool，分别负责不同的提示构建逻辑。

```yaml examples/rag_loop.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="19,29" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark
  retriever: servers/retriever
  prompt: servers/prompt
  generation: servers/generation
  evaluation: servers/evaluation
  custom: servers/custom

# MCP Client Pipeline
pipeline:
- benchmark.get_data
- retriever.retriever_init
- generation.generation_init
- retriever.retriever_search
- loop:
    times: 3
    steps:
    - prompt.gen_subq
    - generation.generate:
        output:
          ans_ls: subq_ls
    - retriever.retriever_search:
        input:
          query_list: subq_ls
        output:
          ret_psg: temp_psg
    - custom.merge_passages
- prompt.qa_rag_boxed
- generation.generate
- custom.output_extract_from_boxed
- evaluation.evaluate
```

若希望为不同任务加载不同模板，需在注册时为每个 Prompt Tool 指定独立的模板字段名：

```python servers/prompt/src/prompt.py icon="python" highlight="1,13" theme={null}
@app.prompt(output="q_ls,ret_psg,template->prompt_ls")
def qa_rag_boxed(
    q_ls: List[str], ret_psg: List[str | Any], template: str | Path
) -> list[PromptMessage]:
    template: Template = load_prompt_template(template)
    ret = []
    for q, psg in zip(q_ls, ret_psg):
        passage_text = "\n".join(psg)
        p = template.render(question=q, documents=passage_text)
        ret.append(p)
    return ret

@app.prompt(output="q_ls,ret_psg,gen_subq_template->prompt_ls")
def gen_subq(
    q_ls: List[str],
    ret_psg: List[str | Any],
    template: str | Path,
) -> List[PromptMessage]:
    template: Template = load_prompt_template(template)
    all_prompts = []
    for q, psg in zip(q_ls, ret_psg):
        passage_text = "\n".join(psg)
        p = template.render(question=q, documents=passage_text)
        all_prompts.append(p)
    return all_prompts
```

随后，在 `servers/prompt/parameter.yaml` 中添加对应模板字段：

<Note>请确保在执行 build 命令前完成此修改。</Note>

```yaml servers/prompt/parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b"  theme={null}
# servers/prompt/parameter.yaml

# QA
template: prompt/qa_boxed.jinja

# RankCoT
kr_template: prompt/RankCoT_knowledge_refinement.jinja
qa_template: prompt/RankCoT_question_answering.jinja

# Search-R1
search_r1_gen_template: prompt/search_r1_append.jinja

# R1-Searcher
r1_searcher_gen_template: prompt/r1_searcher_append.jinja

# For other prompts, please add parameters here as needed

# Take webnote as an example:
webnote_gen_plan_template: prompt/webnote_gen_plan.jinja
webnote_init_page_template: prompt/webnote_init_page.jinja
webnote_gen_subq_template: prompt/webnote_gen_subq.jinja
webnote_fill_page_template: prompt/webnote_fill_page.jinja
webnote_gen_answer_template: prompt/webnote_gen_answer.jinja

gen_subq_template: prompt/gen_subq.jinja  # [!code ++]
```

运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build rag_loop.yaml
```

系统会自动在生成的参数文件中注册新字段：

```yaml examples/rag_loop_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="3" theme={null}
...
prompt:
  gen_subq_template: prompt/gen_subq.jinja
  template: prompt/qa_boxed.jinja
retriever:
  backend: sentence_transformers
...
```

随后即可正常执行该 Pipeline。


> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Generation

## 作用

Generation Server 是 UltraRAG 中负责 调用和部署大语言模型（LLM） 的核心模块。
它接收来自 Prompt Server 构建的输入提示（Prompt），并生成相应的输出结果。
该模块支持 文本生成 与 图像-文本多模态生成 两种模式，可灵活适配不同任务场景（如问答、推理、总结、视觉问答等）。

Generation Server 原生兼容以下主流后端：[vLLM](https://github.com/vllm-project/vllm)、[HuggingFace](https://github.com/huggingface/transformers)
以及 [OpenAI](https://platform.openai.com/docs/quickstart)。

## 使用示例

### 文本生成

以下示例展示了如何使用 Generation Server 执行一个基础的文本生成任务。该流程通过 Prompt Server 构建输入提示后，调用 LLM 生成回答，并最终完成结果提取与评估。

```yaml examples/vanilla_llm.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="5,12,14" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark
  prompt: servers/prompt
  generation: servers/generation
  evaluation: servers/evaluation
  custom: servers/custom

# MCP Client Pipeline
pipeline:
- benchmark.get_data
- generation.generation_init
- prompt.qa_boxed
- generation.generate
- custom.output_extract_from_boxed
- evaluation.evaluate
```

运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build examples/vanilla_llm.yaml
```

修改参数：

```yaml examples/parameters/vanilla_llm_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
    limit: -1
    name: nq
    path: data/sample_nq_10.jsonl
    seed: 42
    shuffle: false
custom: {}
evaluation:
  metrics:
  - acc
  - f1
  - em
  - coverem
  - stringem
  - rouge-1
  - rouge-2
  - rouge-l
  save_path: output/evaluate_results.json
generation:
  backend: vllm
  backend_configs:
    hf:
      batch_size: 8
      gpu_ids: 2,3
      model_name_or_path: openbmb/MiniCPM4-8B
      trust_remote_code: true
    openai:
      api_key: abc
      base_delay: 1.0
      base_url: http://localhost:8000/v1
      concurrency: 8
      model_name: MiniCPM4-8B
      retries: 3
    vllm:
      dtype: auto
      gpu_ids: 2,3
      gpu_memory_utilization: 0.9
      model_name_or_path: openbmb/MiniCPM4-8B
      trust_remote_code: true
  extra_params:
    chat_template_kwargs:
      enable_thinking: false
  sampling_params:
    max_tokens: 2048
    temperature: 0.7
    top_p: 0.8
  system_prompt: ''
prompt:
  template: prompt/qa_boxed.jinja
```

运行 Pipeline：

```shell theme={null}
ultrarag run examples/vanilla_llm.yaml
```

### 多模态推理

在多模态场景下，Generation Server 不仅可以处理文本输入，还能结合图像等视觉信息完成更复杂的推理任务。下面通过一个示例展示如何实现。

我们先准备一个示例数据集（包含图像路径）：

```json data/test.jsonl icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": 0, "question": "when was the last time anyone was on the moon", "golden_answers": ["14 December 1972 UTC", "December 1972"], "image":["image/page_0.jpg"],"meta_data": {}}
```

在进行多模态生成前，需要在 Benchmark Server 的 `get_data` 函数中新增字段 `multimodal_path`，
用于指定图像输入路径。
<Note>如何新增字段请参考[新增加载数据集字段](/pages/cn/rag_servers/benchmark)。</Note>

```yaml examples/vanilla_vlm.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="5,12,14" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark
  prompt: servers/prompt
  generation: servers/generation
  evaluation: servers/evaluation
  custom: servers/custom

# MCP Client Pipeline
pipeline:
- benchmark.get_data
- generation.generation_init
- prompt.qa_boxed
- generation.multimodal_generate
- custom.output_extract_from_boxed
- evaluation.evaluate
```

运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build examples/vanilla_vlm.yaml
```

修改参数：

```yaml examples/parameters/vanilla_vlm_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
      multimodal_path: image # [!code ++]
    limit: -1
    name: nq # [!code --]
    path: data/sample_nq_10.jsonl # [!code --]
    name: test # [!code ++]
    path: data/test.jsonl # [!code ++]
    seed: 42
    shuffle: false
custom: {}
evaluation:
  metrics:
  - acc
  - f1
  - em
  - coverem
  - stringem
  - rouge-1
  - rouge-2
  - rouge-l
  save_path: output/evaluate_results.json
generation:
  backend: vllm
  backend_configs:
    hf:
      batch_size: 8
      gpu_ids: 2,3
      model_name_or_path: openbmb/MiniCPM4-8B
      trust_remote_code: true
    openai:
      api_key: abc
      base_delay: 1.0
      base_url: http://localhost:8000/v1
      concurrency: 8
      model_name: MiniCPM4-8B
      retries: 3
    vllm:
      dtype: auto
      gpu_ids: 2,3
      gpu_memory_utilization: 0.9
      model_name_or_path: openbmb/MiniCPM4-8B # [!code --]
      model_name_or_path: openbmb/MiniCPM-V-4 # [!code ++]
      trust_remote_code: true
  extra_params:
    chat_template_kwargs:
      enable_thinking: false
  image_tag: null
  sampling_params:
    max_tokens: 2048
    temperature: 0.7
    top_p: 0.8
  system_prompt: ''
prompt:
  template: prompt/qa_boxed.jinja
```

运行：

```shell theme={null}
ultrarag run examples/vanilla_vlm.yaml
```

<Tip>注意：你可以设置 `image_tag` 如 `<IMG>` 来指定你希望图像输入的位置，为空默认为最左侧输入。</Tip>

### 部署模型

UltraRAG 完全兼容 OpenAI API 接口规范，因此任何符合该接口标准的模型都可以直接接入，无需额外适配或修改代码。
以下示例展示如何使用 [vLLM](https://docs.vllm.ai/en/latest/cli/serve.html#parallelconfig) 部署本地模型。

**step1: 后台部署模型**

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

**Step 2：修改 Pipeline 参数**

修改参数：

```yaml examples/parameters/vanilla_llm_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
    limit: -1
    name: nq
    path: data/sample_nq_10.jsonl
    seed: 42
    shuffle: false
custom: {}
evaluation:
  metrics:
  - acc
  - f1
  - em
  - coverem
  - stringem
  - rouge-1
  - rouge-2
  - rouge-l
  save_path: output/evaluate_results.json
generation:
  backend: vllm # [!code --]
  backend: openai # [!code ++]
  backend_configs:
    hf:
      batch_size: 8
      gpu_ids: 2,3
      model_name_or_path: openbmb/MiniCPM4-8B
      trust_remote_code: true
    openai:
      api_key: abc
      base_delay: 1.0
      base_url: http://localhost:8000/v1 # [!code --]
      base_url: http://127.0.0.1:65501/v1 # [!code ++]
      concurrency: 8
      model_name: MiniCPM4-8B # [!code --]
      model_name: qwen3-8b # [!code ++]
      retries: 3
    vllm:
      dtype: auto
      gpu_ids: 2,3
      gpu_memory_utilization: 0.9
      model_name_or_path: openbmb/MiniCPM4-8B
      trust_remote_code: true
  extra_params:
    chat_template_kwargs:
      enable_thinking: false
  sampling_params:
    max_tokens: 2048
    temperature: 0.7
    top_p: 0.8
  system_prompt: ''
prompt:
  template: prompt/qa_boxed.jinja
```

完成配置后，即可正常运行.


> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Evaluation

## 作用

Evaluation Server 提供了一套完善的自动化评估工具，
用于对检索与生成任务的模型输出进行系统化、可复现的性能评测。
它支持多种主流指标，包括排序类、匹配类与摘要类评估，可直接嵌入 Pipeline 末尾，实现评估结果的自动计算与保存。

### 检索

| 指标名         | 类型    | 说明                                                                |
| :---------- | :---- | :---------------------------------------------------------------- |
| `MRR`       | float | Mean Reciprocal Rank（平均倒数排名），衡量首个相关文档的平均排名位置。                     |
| `MAP`       | float | Mean Average Precision（平均精确率），综合考虑检索的精确性与召回率。                     |
| `Recall`    | float | 召回率，衡量检索系统能找回多少相关文档。                                              |
| `Precision` | float | 精确率，衡量检索结果中有多少是相关文档。                                              |
| `NDCG`      | float | Normalized Discounted Cumulative Gain（标准化折损累计增益），评估检索结果与理想排序的一致性。 |

### 生成

| 指标名        | 类型    | 说明                                            |
| :--------- | ----- | :-------------------------------------------- |
| `EM`       | float | Exact Match，预测与任一参考完全相同。                      |
| `Acc`      | float | Answer 包含参考答案中的任一形式（宽松匹配）。                    |
| `StringEM` | float | 针对多组答案的软匹配比例（常用于多选/嵌套 QA）。                    |
| `CoverEM`  | float | 参考答案是否完全被预测文本覆盖。                              |
| `F1`       | float | Token 级别 F1 得分。                               |
| `Rouge_1`  | float | 1-gram ROUGE-F1。                              |
| `Rouge_2`  | float | 2-gram ROUGE-F1。                              |
| `Rouge_L`  | float | Longest Common Subsequence (LCS) based ROUGE。 |

## 使用示例

### 检索

#### Trec文件评估

在信息检索中，TREC 格式文件 是标准化的评测接口，用于衡量模型在排序、召回等方面的性能。
TREC 评估通常由两类文件组成：qrel（人工标注的真实相关性）与 run（系统检索输出结果）。

**一、qrel 文件（“ground truth”，人工标注的相关性）**

qrel 文件用于存储“哪些文档与哪个查询是相关的”这类人工标注的真实相关性判断。\
在评测时，系统输出的检索结果会与 qrel 文件进行对比，用来计算指标（如 MAP、NDCG、Recall、Precision 等）。

格式（4列，空格分隔）：

```
<query_id>  <iter>  <doc_id>  <relevance>
```

* `query_id`：查询编号
* `iter`：通常写 `0`（历史遗留字段，可忽略）
* `doc_id`：文档编号
* `relevance`：相关性标注（通常 0 表示不相关，1 或更高表示相关）

示例：

```
1 0 DOC123 1
1 0 DOC456 0
2 0 DOC321 1
2 0 DOC654 1
```

**二、run 文件（系统输出的检索结果）**

run 文件保存检索系统的输出结果，用于与 qrel 文件对比评估性能。\
每行表示一个查询返回的文档及其得分信息。

格式（6列，空格分隔）：

```
<query_id>  Q0  <doc_id>  <rank>  <score>  <run_name>
```

* `query_id`：查询编号
* `Q0`：固定写 `Q0`（TREC 标准要求）
* `doc_id`：文档编号
* `rank`：排序名次（1 表示最相关）
* `score`：系统打分
* `run_name`：系统名称（例如 bm25、dense\_retriever）

示例：

```
1 Q0 DOC123 1 12.34 bm25
1 Q0 DOC456 2 11.21 bm25
2 Q0 DOC654 1 13.89 bm25
2 Q0 DOC321 2 12.01 bm25
```

<Note>你可以点击以下链接下载示例文件：[qrels.test](https://github.com/usnistgov/trec_eval/blob/main/test/qrels.test) 和 [results.test](https://github.com/usnistgov/trec_eval/blob/main/test/results.test)</Note>

```yaml examples/eval_trec.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  evaluation: servers/evaluation

# MCP Client Pipeline
pipeline:
- evaluation.evaluate_trec
```

运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build examples/eval_trec.yaml
```

```yaml examples/parameters/eval_trec_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
evaluation:
  ir_metrics:
  - mrr
  - map
  - recall
  - ndcg
  - precision
  ks:
  - 1
  - 5
  - 10
  - 20
  - 50
  - 100
  qrels_path: data/qrels.txt # [!code --]
  run_path: data/run_a.txt # [!code --]
  qrels_path: data/qrels.test # [!code ++]
  run_path: data/results.test # [!code ++]
  save_path: output/evaluate_results.json

```

运行以下命令执行该 Pipeline：

```shell theme={null}
ultrarag run examples/eval_trec.yaml
```

#### 显著性分析

显著性分析（Significance Testing）用于判断两个检索系统之间的性能差异是否“真实存在”，而不是由随机波动造成。\
它回答的核心问题是：系统 A 的提升是否具有统计学意义？

在检索任务中，系统的性能通常通过多个查询的平均指标（如 MAP、NDCG、Recall 等）衡量。\
然而，平均值的提升并不一定可靠，因为不同查询间存在随机性。\
显著性分析通过统计检验方法，评估系统改进是否稳定且可复现。

常见的显著性分析方法包括：

* **置换检验（Permutation Test）**：通过随机交换系统 A 和系统 B 的查询结果多次（如 10000 次），构建差异的随机分布。若实际差异超过 95% 的随机情况（p \< 0.05），则认为提升显著。
* **t 检验（Paired t-test）**：假设两个系统的查询得分服从正态分布，计算两者均值差异的显著性。

UltraRAG 内置 双侧置换检验（Two-sided Permutation Test），在自动评估过程中输出以下关键统计信息：

* **A\_mean / B\_mean** 表示新旧系统的平均指标；
* **Diff(A-B)** 表示改进幅度；
* **p\_value** 为显著性检验的概率；
* **significant** 为显著性判断（p \< 0.05 时为 True）。

```yaml examples/eval_trec_pvalue.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  evaluation: servers/evaluation

# MCP Client Pipeline
pipeline:
- evaluation.evaluate_trec_pvalue
```

运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build examples/eval_trec_pvalue.yaml
```

```yaml examples/parameters/eval_trec_pvalue_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
evaluation:
  ir_metrics:
  - mrr
  - map
  - recall
  - ndcg
  - precision
  ks:
  - 1
  - 5
  - 10
  - 20
  - 50
  - 100
  n_resamples: 10000
  qrels_path: data/qrels.txt
  run_new_path: data/run_a.txt
  run_old_path: data/run_b.txt
  save_path: output/evaluate_results.json
```

运行以下命令执行该 Pipeline：

```shell theme={null}
ultrarag run examples/eval_trec_pvalue.yaml
```

### 生成

#### 基本用法

```yaml examples/rag_full.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="5,19" theme={null}
servers:
  benchmark: servers/benchmark
  retriever: servers/retriever
  prompt: servers/prompt
  generation: servers/generation
  evaluation: servers/evaluation
  custom: servers/custom

pipeline:
- benchmark.get_data
- retriever.retriever_init
- retriever.retriever_embed
- retriever.retriever_index
- retriever.retriever_search
- generation.generation_init
- prompt.qa_rag_boxed
- generation.generate
- custom.output_extract_from_boxed
- evaluation.evaluate
```

只需在 Pipeline 的末尾添加 evaluation.evaluate 工具，即可在任务执行完成后自动计算所有指定评测指标，并输出结果到配置文件中设定的路径。

#### 评估已有结果

如果你已经拥有模型生成的结果文件，并希望直接对其进行评估，可以将结果整理为标准化的 JSONL 格式。文件中应至少包含代表答案标签与生成结果的字段，例如：

```json icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/json.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=81a8c440100333f3454ca984a5b0fe5a" theme={null}
{"id": 0, "question": "when was the last time anyone was on the moon", "golden_answers": ["14 December 1972 UTC", "December 1972"], "pred_answer": "December 14, 1973"}
{"id": 1, "question": "who wrote he ain't heavy he's my brother lyrics", "golden_answers": ["Bobby Scott", "Bob Russell"], "pred_answer": "The documents do not provide information about the author of the lyrics to \"He Ain't Heavy, He's My Brother.\""}
```

```yaml examples/evaluate_results.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark
  evaluation: servers/evaluation

# MCP Client Pipeline
pipeline:
- benchmark.get_data
- evaluation.evaluate
```

为了让 Benchmark Server 读取生成结果，需要在 get\_data 函数中增加 `pred_ls` 字段：

```python servers/prompt/src/benchmark.py icon="python" theme={null}
@app.tool(output="benchmark->q_ls,gt_ls") # [!code --]
@app.tool(output="benchmark->q_ls,gt_ls,pred_ls") # [!code ++]
def get_data(
    benchmark: Dict[str, Any],
) -> Dict[str, List[Any]]:
```

然后，运行以下命令编译 Pipeline：

```shell theme={null}
ultrarag build examples/evaluate_results.yaml
```

在生成的参数文件中，新增字段 pred\_ls 并指定其在原始数据中的对应键名，同时修改数据路径和名称以指向新的评估文件：

```yaml examples/parameters/evaluate_results_parameter.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" theme={null}
benchmark:
  benchmark:
    key_map:
      gt_ls: golden_answers
      q_ls: question
      pred_ls: pred_answer  # [!code ++]
    limit: -1
    name: nq  # [!code --]
    path: data/sample_nq_10.jsonl # [!code --]
    name: evaluate  # [!code ++]
    path: data/test_evaluate.jsonl # [!code ++]
    seed: 42
    shuffle: false
evaluation:
  metrics:
  - acc
  - f1
  - em
  - coverem
  - stringem
  - rouge-1
  - rouge-2
  - rouge-l
  save_path: output/evaluate_results.json
```

运行以下命令执行该 Pipeline：

```shell theme={null}
ultrarag run examples/evaluate_results.yaml
```

> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Router

<Note>本小节建议结合教程 [分支型结构](/pages/cn/rag_client/branch) 一起学习。</Note>

## 作用

在复杂的 RAG 推理任务 中，常常需要根据中间结果（例如模型当前的生成内容或检索结果）动态决定后续执行路径。
Router Server 正是为此而设计的关键组件——它根据输入信息对当前状态进行判断，并返回一个自定义的分支标签（状态标识），用于驱动 Pipeline 中的分支跳转与动态控制。

## 实现示例

下面通过一个简单示例，展示如何实现 Router Tool。

假设当前的 RAG 流程中，需要模型判断当前检索到的文档是否已包含足够信息回答问题：若信息充足则结束流程，否则继续执行检索。

可以这样实现一个 Router Tool：

```python servers/router/src/router.py icon="python" theme={null}
@app.tool(output="ans_ls->ans_ls")
def check_model_state(ans_ls: List[str]) -> Dict[str, List[Dict[str, str]]]:
    def check_state(text):
        if "<search>" in text:
            return True
        else:
            return False
    ans_ls = [
        {
            "data": answer,
            "state": "continue" if check_state(answer) else "stop",
        }
        for answer in ans_ls
    ]
    return {"ans_ls": ans_ls}
```

该 Tool 会为每条回答打上状态标签，用于引导后续流程执行：

* `continue`：信息不足，需继续检索；
* `stop`：信息已足够，可终止流程。

## 调用示例

定义好的 `Router Tool` 需要与分支结构 `branch:` 和 `router:` 搭配使用，共同实现基于状态标签的动态跳转。

```yaml examples/rag_branch.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="9,24,26,37" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark
  retriever: servers/retriever
  prompt: servers/prompt
  generation: servers/generation
  evaluation: servers/evaluation
  custom: servers/custom
  router: servers/router

# MCP Client Pipeline
pipeline:
- benchmark.get_data
- retriever.retriever_init
- generation.generation_init
- retriever.retriever_search
- loop:
    times: 10
    steps:
    - prompt.check_passages
    - generation.generate
    - branch:
        router:
        - router.check_model_state
        branches:
          continue:
          - prompt.gen_subq
          - generation.generate:
              output:
                ans_ls: subq_ls
          - retriever.retriever_search:
              input:
                query_list: subq_ls
              output:
                ret_psg: temp_psg
          - custom.merge_passages
          stop: []
- prompt.qa_rag_boxed
- generation.generate
- custom.output_extract_from_boxed
- evaluation.evaluate
```

该示例展示了一个典型的循环推理流程：
当 `router.check_model_state` 判断模型输出包含 `<search>` 标识时，进入 `continue` 分支继续检索；
否则进入 `stop` 分支直接结束循环。


> ## Documentation Index
> Fetch the complete documentation index at: https://ultrarag.openbmb.cn/llms.txt
> Use this file to discover all available pages before exploring further.

# Custom

## 作用

Custom Server 用于存放那些无法归入标准模块（如 Retriever、Generation、Evaluation 等）的自定义工具函数。
它为开发者提供了一个灵活的扩展空间，可用于实现各种与核心 RAG 模块配合的逻辑组件，例如：

* 数据清洗与预处理
* 关键词提取或特征构造
* 特定任务逻辑（如答案抽取、格式化、过滤等）

<Note>Custom Server 是你的自由工具箱——任何不属于核心 Server 的功能逻辑，都可以在这里定义与复用。</Note>

## 实现示例

下面以一个常见示例 output\_extract\_from\_boxed 为例，展示如何自定义并注册一个 Tool。

```python servers/custom/src/custom.py icon="python" theme={null}
@app.tool(output="ans_ls->pred_ls")
def output_extract_from_boxed(ans_ls: List[str]) -> Dict[str, List[str]]:
    def extract(ans: str) -> str:
        start = ans.rfind(r"\boxed{")
        if start == -1:
            content = ans.strip()
        else:
            i = start + len(r"\boxed{")
            brace_level = 1
            end = i
            while end < len(ans) and brace_level > 0:
                if ans[end] == "{":
                    brace_level += 1
                elif ans[end] == "}":
                    brace_level -= 1
                end += 1
            content = ans[i : end - 1].strip()
            content = re.sub(r"^\$+|\$+$", "", content).strip()
            content = re.sub(r"^\\\(|\\\)$", "", content).strip()
            if content.startswith(r"\text{") and content.endswith("}"):
                content = content[len(r"\text{") : -1].strip()
            content = content.strip("()").strip()

        content = content.replace("\\", " ")
        content = content.replace("  ", " ")
        return content

    return {"pred_ls": [extract(ans) for ans in ans_ls]}
```

该工具的功能是从模型输出字符串中提取 `\boxed{...}` 格式的最终答案文本，
输出结果会映射到变量 `pred_ls`，供下游评测或后处理模块使用。

## 调用示例

定义好自定义工具后，只需在 Pipeline 中注册 custom 模块并调用对应的 Tool 即可：

```yaml examples/rag_full.yaml icon="https://mintcdn.com/ultrarag/T7GffHzZitf6TThi/images/yaml.svg?fit=max&auto=format&n=T7GffHzZitf6TThi&q=85&s=69b41e79144bc908039c2ee3abbb1c3b" highlight="8,20" theme={null}
# MCP Server
servers:
  benchmark: servers/benchmark
  retriever: servers/retriever
  prompt: servers/prompt
  generation: servers/generation
  evaluation: servers/evaluation
  custom: servers/custom

# MCP Client Pipeline
pipeline:
- benchmark.get_data
- retriever.retriever_init
- retriever.retriever_embed
- retriever.retriever_index
- retriever.retriever_search
- generation.generation_init
- prompt.qa_rag_boxed
- generation.generate
- custom.output_extract_from_boxed
- evaluation.evaluate
```

在此示例中，custom.output\_extract\_from\_boxed 被用于从模型输出中提取标准化答案，
随后交由 evaluation.evaluate 进行评测。
