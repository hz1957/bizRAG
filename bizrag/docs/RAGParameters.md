# BizRAG RAG 参数速查

每个变量单独一行，顺序是：变量名、中文注释、配置入口。

## 切块与写入

- `parse_file_path`：待解析的原始文件路径。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `text_corpus_save_path`：文本语料 JSONL 输出路径。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `image_corpus_save_path`：图片语料 JSONL 输出路径。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `mineru_dir`：MinerU 解析产物目录。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `mineru_extra_params.source`：MinerU 模型来源。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `raw_chunk_path`：原始 chunk 输入语料路径。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `chunk_path`：最终 chunk 输出路径。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `use_title`：切块时是否把标题并入正文。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `chunk_backend`：切块算法，支持 `token` / `sentence` / `recursive`。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `tokenizer_or_token_counter`：切块长度计数方式。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `chunk_size`：单个 chunk 的目标长度。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `chunk_backend_configs.token.chunk_overlap`：token 切块的重叠长度。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `chunk_backend_configs.sentence.chunk_overlap`：句子切块的重叠长度。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `chunk_backend_configs.sentence.min_sentences_per_chunk`：每个句子 chunk 至少包含的句子数。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `chunk_backend_configs.sentence.delim`：句子切分分隔符。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `chunk_backend_configs.recursive.min_characters_per_chunk`：递归切块时每块最少字符数。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)

## 检索与索引

- `model_name_or_path`：主检索模型名称或路径。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_model_name_or_path`：retriever 显式指定的模型名称或路径。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `corpus_path`：检索语料文件路径。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_corpus_path`：retriever 专用语料路径。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `embedding_path`：embedding 向量文件路径。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_embedding_path`：retriever 专用 embedding 文件路径。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `collection_name`：向量库 collection 名称。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_collection_name`：retriever 专用 collection 名称。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend`：检索后端类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_backend`：retriever 显式指定的后端类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.infinity.bettertransformer`：Infinity 是否启用 BetterTransformer。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.infinity.pooling_method`：Infinity 的 pooling 策略。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.infinity.model_warmup`：Infinity 启动时是否预热模型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.infinity.trust_remote_code`：Infinity 是否信任远程模型代码。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.sentence_transformers.trust_remote_code`：SentenceTransformers 是否信任远程代码。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.sentence_transformers.local_files_only`：SentenceTransformers 是否只读本地模型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.sentence_transformers.sentence_transformers_encode.normalize_embeddings`：是否归一化 embedding。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.sentence_transformers.sentence_transformers_encode.encode_chunk_size`：编码时每批 chunk 数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.sentence_transformers.sentence_transformers_encode.q_prompt_name`：查询编码时使用的 prompt 名。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.sentence_transformers.sentence_transformers_encode.psg_prompt_name`：文档编码时使用的 prompt 名。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.sentence_transformers.sentence_transformers_encode.psg_task`：文档编码任务类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.sentence_transformers.sentence_transformers_encode.q_task`：查询编码任务类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.openai.model_name`：OpenAI embedding 模型名。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.openai.base_url`：OpenAI embedding 接口地址。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.openai.api_key`：OpenAI embedding 密钥。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.openai.concurrency`：OpenAI embedding 并发数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.bm25.lang`：BM25 分词语言。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `backend_configs.bm25.save_path`：BM25 倒排索引保存路径。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend`：索引后端类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_index_backend`：retriever 显式指定的索引后端。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.faiss.index_use_gpu`：Faiss 建索引时是否用 GPU。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.faiss.index_chunk_size`：Faiss 分批建索引的批大小。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.faiss.index_path`：Faiss 索引文件路径。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.uri`：Milvus 连接地址。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.token`：Milvus 认证 token。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.id_field_name`：Milvus 主键字段名。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.vector_field_name`：Milvus 向量字段名。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.text_field_name`：Milvus 文本字段名。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.id_max_length`：Milvus 主键最大长度。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.text_max_length`：Milvus 文本最大长度。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.metric_type`：Milvus 相似度度量类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.index_params.index_type`：Milvus 索引类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.index_params.metric_type`：Milvus 建索引时的度量类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.search_params.metric_type`：Milvus 查询时的度量类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.search_params.params`：Milvus 查询附加参数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `index_backend_configs.milvus.index_chunk_size`：Milvus 分批写入索引的批大小。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend`：联网搜索后端类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.exa.api_key`：Exa 搜索密钥。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.exa.retries`：Exa 重试次数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.exa.base_delay`：Exa 重试基础退避时间。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.exa.search_kwargs`：Exa 搜索附加参数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.tavily.api_key`：Tavily 搜索密钥。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.tavily.retries`：Tavily 重试次数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.tavily.base_delay`：Tavily 重试基础退避时间。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.tavily.search_kwargs`：Tavily 搜索附加参数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.api_key`：智谱联网搜索密钥。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.base_url`：智谱联网搜索接口地址。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.search_engine`：智谱搜索引擎类型。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.search_intent`：智谱是否启用意图搜索。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.search_recency_filter`：智谱时间过滤策略。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.content_size`：智谱返回内容长度档位。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.retries`：智谱搜索重试次数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.base_delay`：智谱搜索基础退避时间。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `websearch_backend_configs.zhipuai.search_kwargs`：智谱搜索附加参数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `batch_size`：检索编码批大小。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_batch_size`：retriever 显式指定的编码批大小。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `top_k`：默认召回数量。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retrieval_top_k`：检索阶段实际召回数量。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `gpu_ids`：检索模型使用的 GPU 编号。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_gpu_ids`：retriever 显式指定的 GPU 编号。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `query_instruction`：查询前置指令模板。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `is_multimodal`：是否启用多模态检索。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_is_multimodal`：retriever 显式指定的多模态开关。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `overwrite`：重建索引时是否覆盖已有索引。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retrieve_thread_num`：检索线程数。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_url`：检索服务地址。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `is_demo`：是否启用 demo 模式。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_is_demo`：retriever 显式指定的 demo 模式开关。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `query_list`：批量查询输入列表。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `filters`：检索过滤条件。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `output_fields`：检索输出字段白名单。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `filter_expr`：检索过滤表达式。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_backend_configs`：运行时覆写的 retriever backend 配置。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever_index_backend_configs`：运行时覆写的索引后端配置。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)

## 重排

- `model_name_or_path`：重排模型名称或路径。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend`：重排后端类型。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.infinity.bettertransformer`：Infinity 重排是否启用 BetterTransformer。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.infinity.pooling_method`：Infinity 重排 pooling 策略。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.infinity.device`：Infinity 重排运行设备。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.infinity.model_warmup`：Infinity 重排是否预热模型。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.infinity.trust_remote_code`：Infinity 重排是否信任远程代码。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.sentence_transformers.device`：SentenceTransformers 重排运行设备。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.sentence_transformers.trust_remote_code`：SentenceTransformers 重排是否信任远程代码。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.sentence_transformers.local_files_only`：SentenceTransformers 重排是否只读本地模型。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.openai.model_name`：OpenAI 重排模型名。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.openai.base_url`：OpenAI 重排接口地址。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `backend_configs.openai.api_key`：OpenAI 重排密钥。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `gpu_ids`：重排模型使用的 GPU 编号。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `top_k`：默认保留的重排结果数量。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `reranker_top_k`：重排阶段实际保留数量。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `batch_size`：重排批大小。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `query_instruction`：重排时的查询指令。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `query_list`：批量重排的查询列表。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `ret_items`：待重排的检索结果列表。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `passages_list`：待重排的纯文本段落列表。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)

## 多路召回融合

- `query`：融合阶段输入查询。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `top_k`：默认返回数量。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `query_instruction`：融合阶段查询指令。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `filters`：融合阶段过滤条件。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `output_fields`：融合阶段输出字段。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `retriever_top_k`：召回阶段候选数量。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `retriever_query_instruction`：召回阶段使用的查询指令。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `merge_top_k`：融合后保留的候选数量。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `strategy`：融合策略，如 `rrf`。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `rrf_k`：RRF 融合的平滑常数。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `primary_weight`：主检索通道权重。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `secondary_weight`：次检索通道权重。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)

## Prompt

- `q_ls`：Prompt 阶段输入的问题列表。 [bizrag/servers/prompt/parameter.yaml](../servers/prompt/parameter.yaml)
- `ret_psg`：Prompt 阶段输入的检索段落列表。 [bizrag/servers/prompt/parameter.yaml](../servers/prompt/parameter.yaml)
- `template`：使用的 Prompt 模板文件。 [bizrag/servers/prompt/parameter.yaml](../servers/prompt/parameter.yaml)

## 生成

- `backend`：生成后端类型。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `backend_configs.openai.model_name`：生成模型名。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `backend_configs.openai.base_url`：生成接口地址。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `backend_configs.openai.api_key`：生成接口密钥。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `sampling_params.temperature`：生成温度。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `sampling_params.top_p`：生成 top-p 采样值。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `sampling_params.max_tokens`：单次生成最大 token 数。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `extra_params`：透传给生成后端的附加参数。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `system_prompt`：系统提示词。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)
- `prompt_ls`：待生成的 prompt 列表。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)

## 请求层仍保留的参数

- `RetrieveRequest.kb_id`：本次检索的知识库 ID。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RetrieveRequest.query`：本次检索问题。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RetrieveRequest.top_k`：本次检索返回条数。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RetrieveRequest.query_instruction`：本次检索额外指令。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RetrieveRequest.filters`：本次检索过滤条件。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RAGRequest.kb_id`：本次问答使用的知识库 ID。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RAGRequest.query`：本次问答问题。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RAGRequest.top_k`：本次问答召回条数。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RAGRequest.query_instruction`：本次问答检索指令。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RAGRequest.filters`：本次问答过滤条件。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `RAGRequest.system_prompt`：本次问答临时系统提示词。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractFieldSpec.name`：抽取字段名。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractFieldSpec.description`：抽取字段说明。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractFieldSpec.type`：抽取字段类型。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractFieldSpec.aliases`：抽取字段别名列表。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractFieldSpec.required`：抽取字段是否必填。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractFieldSpec.enum_values`：抽取字段枚举值。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractFieldSpec.patterns`：抽取字段正则模式。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractFieldSpec.normalizers`：抽取字段归一化规则。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractRequest.kb_id`：本次抽取使用的知识库 ID。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractRequest.query`：本次抽取问题。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractRequest.fields`：本次抽取字段列表。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractRequest.top_k`：本次抽取召回条数。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractRequest.query_instruction`：本次抽取检索指令。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractRequest.filters`：本次抽取过滤条件。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `ExtractRequest.max_evidence_per_field`：每个字段最多保留的证据数。 [bizrag/contracts/schemas.py](../contracts/schemas.py)
- `DEFAULT_OUTPUT_FIELDS`：默认返回的检索元数据字段。 [bizrag/contracts/schemas.py](../contracts/schemas.py)

## 最常用的调参入口

- `corpus`：切块、标题拼接、chunk overlap。 [bizrag/servers/corpus/parameter.yaml](../servers/corpus/parameter.yaml)
- `retriever`：embedding、Milvus、BM25、默认 top_k。 [bizrag/servers/retriever/parameter.yaml](../servers/retriever/parameter.yaml)
- `retriever(docker)`：Docker 环境检索默认值。 [bizrag/servers/retriever/parameter.docker.yaml](../servers/retriever/parameter.docker.yaml)
- `reranker`：重排模型、重排 top_k、批大小。 [bizrag/servers/reranker/parameter.yaml](../servers/reranker/parameter.yaml)
- `custom`：多路召回融合策略和权重。 [bizrag/servers/custom/parameter.yaml](../servers/custom/parameter.yaml)
- `prompt`：RAG Prompt 模板。 [bizrag/servers/prompt/parameter.yaml](../servers/prompt/parameter.yaml)
- `generation`：生成模型和采样参数。 [bizrag/servers/generation/parameter.yaml](../servers/generation/parameter.yaml)

## 如何高效调整参数

如果你只想站在 RAG 算法视角调参，不想陷入工程细节，推荐把所有实验都压缩成一个固定流程：先固定评测集，再按链路从前往后调，不要同时改多类参数。

### 一套够用的调参原则

- 先定评测集：至少准备 20 到 50 条真实问题，按场景分桶，例如 FAQ、长文档定位、多跳问答、结构化字段抽取。
- 先定指标：检索阶段看 `Recall@k`、`MRR`、`nDCG`；最终问答阶段看答案正确率、证据命中率、幻觉率。
- 单次只改一组参数：例如这一轮只动 chunk，下一轮只动 retriever；否则无法归因。
- 先锁生成，再调检索：调检索时把 `sampling_params.temperature` 降低，尽量减少生成波动。
- 每轮保留 baseline：记录“上一版参数 + 指标 + 失败样本”，不要只看平均分。

### 推荐调参顺序

1. 先调切块
   目标是让“一个 chunk 内的信息语义完整，但不过长”。
   文件入口：[corpus 参数](../servers/corpus/parameter.yaml)
   优先关注 `chunk_backend`、`chunk_size`、`chunk_backend_configs.*.chunk_overlap`、`use_title`。

2. 再调召回
   目标是先把正确答案尽可能召回来。
   文件入口：[retriever 参数](../servers/retriever/parameter.yaml)
   优先关注 `model_name_or_path`、`retriever_model_name_or_path`、`top_k`、`backend_configs.sentence_transformers.sentence_transformers_encode.normalize_embeddings`。

3. 再调重排
   目标是把正确证据尽量排到前面。
   文件入口：[reranker 参数](../servers/reranker/parameter.yaml)
   优先关注 `reranker_top_k`、`top_k`、`batch_size`。

4. 再调多路融合
   目标是提高复杂问题、长尾问题的召回稳定性。
   文件入口：[custom 参数](../servers/custom/parameter.yaml)
   优先关注 `retriever_top_k`、`merge_top_k`、`strategy`、`rrf_k`、`primary_weight`、`secondary_weight`。

5. 最后调 Prompt 和生成
   目标是减少幻觉、提升答案组织质量。
   文件入口：[prompt 参数](../servers/prompt/parameter.yaml) / [generation 参数](../servers/generation/parameter.yaml)
   优先关注 `template`、`system_prompt`、`sampling_params.temperature`、`sampling_params.top_p`、`sampling_params.max_tokens`。

### 各阶段怎么调更快

#### 1. 切块

对应文件：[corpus 参数](../servers/corpus/parameter.yaml)

- 如果答案经常“明明在文档里，但就是召不回来”，先怀疑 chunk，不要先换 embedding。
- `chunk_size` 常用做法是从中等长度开始，然后做三档对比：偏小、居中、偏大。
- `chunk_overlap` 不宜过小，否则跨段信息断裂；也不宜过大，否则冗余变多、排序变差。
- 文档标题有强语义时，优先打开 `use_title`。
- 表格、规章、分点说明多的文档，优先尝试 `sentence` 或 `recursive`；连续自然段文本可先试 `token`。

#### 2. 召回

对应文件：[retriever 参数](../servers/retriever/parameter.yaml)

- 先保证 `Recall@20` 或 `Recall@50` 达标，再看最终答案。
- `top_k` 不要一开始设太小，先放宽召回，再靠 reranker 收缩。
- 如果向量检索对关键词、编号、术语不敏感，可以补 BM25 或做多路召回，而不是只盯 embedding 模型。
- 如果模型本身区分 query/passages 的 prompt 或 task，优先使用 `q_prompt_name`、`psg_prompt_name`、`q_task`、`psg_task` 的官方推荐配置。

#### 3. 重排

对应文件：[reranker 参数](../servers/reranker/parameter.yaml)

- 当召回里已经有正确 chunk，但排名靠后时，再重点调 reranker。
- `reranker_top_k` 的本质是“给重排器多少候选可挑”，过小会错失正确答案，过大则可能引入噪声。
- 若正确答案经常出现在召回前 20 但没进最终前 5，优先调 reranker，而不是继续放大召回 `top_k`。

#### 4. 多路融合

对应文件：[custom 参数](../servers/custom/parameter.yaml)

- 查询类型差异大时，多路召回通常比单一路线更稳。
- `rrf` 适合作为第一版默认融合策略，`rrf_k` 越大，各路排名差距被抹平得越多。
- 一路偏语义、一路偏关键词时，可通过 `primary_weight` / `secondary_weight` 控制主次。
- 如果融合后平均分上升，但头部问题变差，通常说明某一路权重过高或 `merge_top_k` 过大。

#### 5. Prompt 和生成

对应文件：[prompt 参数](../servers/prompt/parameter.yaml) / [generation 参数](../servers/generation/parameter.yaml)

- 检索没解决前，不要过早微调 Prompt。
- 幻觉多时，先收紧 `system_prompt` 和 `template`，明确“只能基于检索证据作答”。
- `temperature` 用于控制稳定性，不是补救检索问题的手段。
- `max_tokens` 太小会截断答案，太大则可能鼓励模型发散。

### 常见症状到参数的快速映射

- 找不到答案：先看 `chunk_size`、`chunk_overlap`、`use_title`、召回 `top_k`。
- 能召回但排不上来：先看 `reranker_top_k`、重排模型、融合权重。
- 关键词问题效果好，语义问题效果差：先看 embedding 模型和 query/passages 编码配置。
- 语义问题效果好，编号/名称/条款问题效果差：补 BM25 或提高关键词通道权重。
- 答案经常有证据但仍乱编：先看 `template`、`system_prompt`、`temperature`。
- 长文档、多跳问题不稳定：先看 chunk 策略，再看多路融合和 reranker。

### 一个低成本实验模板

- 第 1 轮只做切块对比：固定 retriever/reranker/generation，比较 3 组 `chunk_size + overlap`。
- 第 2 轮只做召回对比：固定最佳 chunk，比较不同 embedding 或不同 `top_k`。
- 第 3 轮只做重排对比：固定召回，比较不同 `reranker_top_k` 和重排模型。
- 第 4 轮只做融合对比：比较单路召回和 `rrf` 融合。
- 第 5 轮只做答案质量对比：最后再收敛 Prompt 和 generation。

### 一个实用判断标准

如果你没有很多时间，优先按下面的收益顺序排：

- 第一优先级：`chunk_size`、`chunk_overlap`、`use_title`
- 第二优先级：retriever 模型、召回 `top_k`
- 第三优先级：`reranker_top_k`、重排模型
- 第四优先级：融合策略与权重
- 第五优先级：Prompt 和 generation 采样参数

经验上，RAG 效果的上限通常先由“切块是否合理 + 召回是否覆盖”决定，下限再由“重排是否稳定 + Prompt 是否约束幻觉”决定。
