# UltraRAG Corpus 构建指南

本文档介绍 UltraRAG 中 Corpus 的构建方式，覆盖原始语料生成、MinerU 解析流程，以及 `token`、`sentence`、`recursive` 三种 chunking 策略。

实现入口主要在以下位置：

- `servers/corpus/src/corpus.py`
- `servers/corpus/parameter.yaml`
- `examples/build_text_corpus.yaml`
- `examples/build_image_corpus.yaml`
- `examples/build_mineru_corpus.yaml`
- `examples/corpus_chunk.yaml`

## 1. 整体流程

UltraRAG 的 Corpus 构建通常分成两步：

1. 先把原始文件转成标准 JSONL 语料。
2. 再把文本语料切成适合检索和向量化的 chunk。

常见流程如下：

```text
原始文件
  -> build_text_corpus / build_image_corpus / mineru_parse + build_mineru_corpus
  -> 标准 corpus(JSONL)
  -> chunk_documents
  -> chunks.jsonl
  -> Retriever 向量化和建索引
```

如果你的输入本身已经是符合格式的 JSONL，也可以跳过第一步，直接进入 `chunk_documents`。

## 2. 标准 Corpus 格式

### 2.1 文本 Corpus

文本语料是 JSONL，每行一个文档对象，核心字段如下：

```json
{"id":"doc_001","title":"示例文档","contents":"这里是正文内容"}
```

字段含义：

- `id`: 原始文档 ID
- `title`: 文档标题
- `contents`: 文本内容，后续 chunk 和 embedding 都主要基于它

### 2.2 图片 Corpus

图片语料同样是 JSONL，每行一个图片对象：

```json
{"id":0,"image_id":"report/page_0.jpg","image_path":"image/report/page_0.jpg"}
```

字段含义：

- `id`: 自增 ID
- `image_id`: 图片逻辑标识
- `image_path`: 相对路径

注意：

- Retriever 在多模态模式下会把 `image_path` 视为相对于 corpus JSONL 所在目录的相对路径。
- `build_image_corpus` 生成的图片默认落在 JSONL 同级目录下的 `image/` 子目录。
- `build_mineru_corpus` 生成的图片默认落在 JSONL 同级目录下的 `images/` 子目录。

## 3. 原始语料构建方式

### 3.1 `build_text_corpus`

用于把常见文档批量转换成文本 JSONL。

支持的输入格式：

- 纯文本：`.txt`、`.md`
- Office 文档：`.docx`
- 老式 Word：`.doc`、`.wps`
- PDF/电子书类：`.pdf`、`.xps`、`.oxps`、`.epub`、`.mobi`、`.fb2`

处理逻辑：

- `txt` / `md`：自动识别编码后读取
- `docx`：优先尝试 Office 转换，其次使用 `python-docx` 或直接解析 zip/xml
- `doc` / `wps`：依赖 LibreOffice 或 `soffice` 转成 `docx`
- `pdf` 等格式：通过 `pymupdf` 提取页面文本
- 所有文本会经过 `clean_text()` 和 `reflow_paragraphs()` 清洗

文本清洗主要做两件事：

- 统一换行和空白字符
- 尽量修复 PDF 提取后常见的错误断行、断段和连字符换行

输出格式：

```json
{"id":"UltraRAG","title":"UltraRAG","contents":"清洗后的正文"}
```

一个最小示例：

```yaml
# examples/build_text_corpus.yaml
servers:
  corpus: servers/corpus

pipeline:
- corpus.build_text_corpus
```

配套参数可参考：

```yaml
# examples/parameter/build_text_corpus_parameter.yaml
corpus:
  parse_file_path: data/UltraRAG.pdf
  text_corpus_save_path: corpora/text.jsonl
```

运行方式：

```bash
ultrarag build examples/build_text_corpus.yaml
ultrarag run examples/build_text_corpus.yaml
```

适用场景：

- 知识库文本初始化
- Markdown、TXT、PDF 的快速落库
- 先做文本检索，再做 chunking

### 3.2 `build_image_corpus`

用于把 PDF 每一页渲染成图片，并生成图片 JSONL。

输入限制：

- 只支持单个 PDF 或包含多个 PDF 的目录

处理逻辑：

- 使用 `pymupdf` 按页渲染
- 当前实现按 144 DPI 输出 JPG
- 每个 PDF 的页面图片保存到 `image/<pdf_stem>/page_<n>.jpg`
- 生成 `image_corpus_save_path` 对应的 JSONL

输出示例：

```json
{"id":0,"image_id":"manual/page_0.jpg","image_path":"image/manual/page_0.jpg"}
```

适用场景：

- 多模态检索
- 基于页面图像的视觉问答
- PDF 页面级图文召回

### 3.3 `mineru_parse` + `build_mineru_corpus`

用于处理版面复杂、图文混排明显的 PDF。

这条链路分两步：

1. `mineru_parse`
2. `build_mineru_corpus`

#### 第一步：`mineru_parse`

会执行一条外部命令：

```bash
mineru -p <parse_file_path> -o <mineru_dir> [extra args]
```

其中 `mineru_extra_params` 会被翻译成附加参数，例如：

```yaml
mineru_extra_params:
  source: modelscope
```

会变成：

```bash
--source modelscope
```

#### 第二步：`build_mineru_corpus`

它会读取 MinerU 产物中的：

- `auto/<stem>.md` 作为文本语料
- `auto/images/` 下的图片作为图片语料

然后输出：

- 文本 corpus：`text_corpus_save_path`
- 图片 corpus：`image_corpus_save_path`

示例 pipeline：

```yaml
# examples/build_mineru_corpus.yaml
servers:
  corpus: servers/corpus

pipeline:
- corpus.mineru_parse
- corpus.build_mineru_corpus
```

通用参数可以直接参考：

```yaml
# servers/corpus/parameter.yaml
parse_file_path: data/UltraRAG.pdf
text_corpus_save_path: corpora/text.jsonl
image_corpus_save_path: corpora/image.jsonl

mineru_dir: corpora/
mineru_extra_params:
  source: modelscope
```

适用场景：

- 扫描版 PDF
- 带公式、表格、图片说明的文档
- 希望同时保留 Markdown 文本和页面图片

说明：

- `build_mineru_corpus` 的文本部分不会再次做 `clean_text` / `reflow_paragraphs`
- 它直接使用 MinerU 生成的 Markdown

## 4. Chunking 入口：`chunk_documents`

`chunk_documents` 用于把文本 corpus 切成更细粒度的检索单元。

输入要求：

- `raw_chunk_path` 必须是 JSONL
- 每条记录至少要有 `contents`
- 推荐同时保留 `id` 和 `title`

输出格式：

```json
{"id":0,"doc_id":"UltraRAG","title":"UltraRAG","contents":"Title:\nUltraRAG\n\nContent:\n切分后的正文"}
```

字段含义：

- `id`: chunk 的自增 ID
- `doc_id`: 原始文档 ID
- `title`: 原始文档标题
- `contents`: chunk 后的文本

如果 `use_title: true`，输出内容会被包装成：

```text
Title:
<title>

Content:
<chunk_text>
```

如果 `use_title: false`，则只保留 chunk 本身文本。

## 5. 通用 Chunk 参数

参数示例：

```yaml
corpus:
  raw_chunk_path: corpora/text.jsonl
  chunk_backend_configs:
    token:
      chunk_overlap: 50
    sentence:
      chunk_overlap: 50
      min_sentences_per_chunk: 1
      delim: "['.', '!', '?', '；', '。', '！', '？', '\\n']"
    recursive:
      min_characters_per_chunk: 12
  chunk_backend: sentence
  tokenizer_or_token_counter: character
  chunk_size: 512
  chunk_path: corpora/chunks.jsonl
  use_title: false
```

关键参数说明：

- `chunk_backend`: 选择切分策略，支持 `token`、`sentence`、`recursive`
- `tokenizer_or_token_counter`: 计数方式，可选
  - `word`
  - `character`
  - 任意 `tiktoken` 编码名，例如 `gpt2`
- `chunk_size`: 目标 chunk 大小
- `chunk_path`: 输出文件路径
- `use_title`: 是否把标题拼接到 chunk 内容前面
- `chunk_backend_configs`: 各策略独立参数

关于 tokenizer：

- 当设置为 `word` 或 `character` 时，直接使用对应计数模式
- 其他值会尝试按 `tiktoken.get_encoding()` 加载
- 如果加载失败，当前实现会回退到 `gpt2`

关于 overlap：

- `token` 和 `sentence` 都支持 `chunk_overlap`
- 如果 `chunk_overlap >= chunk_size`，系统会自动调整为 `chunk_size / 4`
- `recursive` 当前实现没有暴露 `chunk_overlap`

## 6. 三种 Chunking 策略

### 6.1 Token Chunking

配置方式：

```yaml
chunk_backend: token
chunk_backend_configs:
  token:
    chunk_overlap: 50
```

实现特点：

- 使用 `chonkie.TokenChunker`
- 严格按 token/word/character 计数切分
- 最容易控制 chunk 长度

优点：

- 长度控制稳定
- 适合 embedding 模型有明确上下文长度约束的情况
- 对大规模语料比较直接

缺点：

- 可能切断句子和段落
- 语义边界不够自然

适用场景：

- 通用检索语料
- 对 chunk 长度上限要求严格
- 更关注吞吐和稳定性，而不是句子完整性

建议：

- 英文语料常配合 `word` 或 `gpt2`
- 中文语料如果不强调精确 token，`character` 通常更直观

### 6.2 Sentence Chunking

配置方式：

```yaml
chunk_backend: sentence
chunk_backend_configs:
  sentence:
    chunk_overlap: 50
    min_sentences_per_chunk: 1
    delim: "['.', '!', '?', '；', '。', '！', '？', '\\n']"
```

实现特点：

- 使用 `chonkie.SentenceChunker`
- 先按句界切分，再在 `chunk_size` 约束下组合成块
- 支持最少句子数和自定义分隔符

当前实现的默认句子分隔符是：

```python
[".", "!", "?", "；", "。", "！", "？"]
```

如果你在参数里显式加上 `\n`，也可以把换行视为额外句界。

优点：

- 语义完整性最好
- 问答、文档检索、知识库说明文更常用
- 相比纯 token 切分，更不容易把短答案切碎

缺点：

- 长句较多时，chunk 大小波动可能更明显
- 句界依赖标点，脏数据上效果受原始文本质量影响

适用场景：

- FAQ
- 说明文档
- 论文、报告、知识库文章

建议：

- 如果源文档来自 PDF 提取，先用 `build_text_corpus` 做文本清洗，再做 sentence chunking
- 中文文档一般优先尝试这一种

### 6.3 Recursive Chunking

配置方式：

```yaml
chunk_backend: recursive
chunk_backend_configs:
  recursive:
    min_characters_per_chunk: 12
```

实现特点：

- 使用 `chonkie.RecursiveChunker`
- 当前实现采用 `RecursiveRules()` 默认规则
- 会优先按更自然的结构边界递归拆分，拆不动时再继续细分

当前实现暴露的主要参数只有：

- `min_characters_per_chunk`

这意味着：

- 你可以控制过短块的下限
- 但不能像 `token` / `sentence` 那样直接配置 overlap
- 递归切分细节主要由 `chonkie` 默认规则决定

优点：

- 对层次化文本更友好
- 比固定长度切分更自然
- 对标题、段落、列表、长短不均的内容更稳

缺点：

- 可解释性不如纯 token 切分直观
- 切分结果更依赖原始文档结构质量

适用场景：

- 层次比较清楚的 Markdown
- 带标题和列表的技术文档
- 希望兼顾自然边界和长度控制

## 7. 如何选择 Chunk 策略

可以按下面的经验来选：

- 默认起步：`sentence`
- 需要最稳定的长度控制：`token`
- 文档结构明显、有标题层级：`recursive`

一个常见实践是：

1. 先用 `sentence`
2. 观察召回质量和 chunk 平均长度
3. 如果 chunk 太碎或太散，再改 `recursive`
4. 如果模型上下文很紧，再回到 `token`

## 8. 推荐参数起点

中文知识库常见起点：

```yaml
chunk_backend: sentence
tokenizer_or_token_counter: character
chunk_size: 512
chunk_backend_configs:
  sentence:
    chunk_overlap: 50
    min_sentences_per_chunk: 1
    delim: "['.', '!', '?', '；', '。', '！', '？', '\\n']"
use_title: false
```

英文知识库常见起点：

```yaml
chunk_backend: token
tokenizer_or_token_counter: gpt2
chunk_size: 256
chunk_backend_configs:
  token:
    chunk_overlap: 32
use_title: false
```

结构化 Markdown 常见起点：

```yaml
chunk_backend: recursive
tokenizer_or_token_counter: character
chunk_size: 512
chunk_backend_configs:
  recursive:
    min_characters_per_chunk: 24
use_title: true
```

## 9. 端到端示例

### 9.1 普通文本/PDF 到 chunk

```bash
ultrarag build examples/build_text_corpus.yaml
ultrarag run examples/build_text_corpus.yaml

ultrarag build examples/corpus_chunk.yaml
ultrarag run examples/corpus_chunk.yaml
```

默认思路：

```text
PDF / TXT / DOCX
  -> corpora/text.jsonl
  -> corpora/chunks.jsonl
```

### 9.2 复杂 PDF 到文本+图片 corpus

```bash
ultrarag build examples/build_mineru_corpus.yaml
ultrarag run examples/build_mineru_corpus.yaml
```

默认思路：

```text
复杂 PDF
  -> MinerU 解析结果
  -> corpora/text.jsonl
  -> corpora/image.jsonl
```

之后你可以：

- 对 `text.jsonl` 继续做 `chunk_documents`
- 对 `image.jsonl` 直接走多模态向量化和索引

## 10. 常见注意事项

### 10.1 MinerU 是可选能力

如果只做普通文本和 PDF 文本提取，不一定需要 MinerU。

如果要使用 `mineru_parse`，建议安装 corpus extra：

```bash
uv sync --extra corpus
```

或者：

```bash
uv pip install -e ".[corpus]"
```

### 10.2 `build_text_corpus` 和 `build_mineru_corpus` 的文本来源不同

- `build_text_corpus`：自己提取纯文本，并做清洗与段落重排
- `build_mineru_corpus`：直接采用 MinerU 的 Markdown 结果

### 10.3 `image_path` 必须保持相对路径可解析

Retriever 在加载图片语料时，会把 `image_path` 拼接到 corpus JSONL 所在目录上。因此：

- 不建议手工改成绝对路径
- 移动 JSONL 文件时，也要同步移动图片目录

### 10.4 `use_title` 会改变最终 embedding 文本

如果开启 `use_title`，每个 chunk 会把标题拼到正文前面。这通常有利于：

- 增强短 chunk 的上下文
- 保留章节语义

但也可能：

- 引入重复前缀
- 拉长每个 chunk 的实际长度

## 11. 推荐实践

如果你刚开始搭知识库，可以按这个顺序做：

1. 普通 PDF / Markdown 先走 `build_text_corpus`
2. 先试 `sentence + character + chunk_size=512`
3. 召回不稳定时再调 `chunk_overlap`
4. 文档结构很强时尝试 `recursive`
5. 扫描版 PDF 或图文复杂文档再引入 MinerU

如果你的目标是最小可用方案，建议先跑通：

```text
build_text_corpus -> chunk_documents -> retriever_embed -> retriever_index
```

这条链路最容易定位问题，也最适合先做检索质量验证。
