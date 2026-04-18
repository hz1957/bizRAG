import asyncio
import os
from typing import Any, Dict, List, Optional, Union

import aiohttp
from tqdm import tqdm

from ultrarag.server import UltraRAG_MCP_Server

app = UltraRAG_MCP_Server("reranker")


class Reranker:
    def __init__(self, mcp_inst: UltraRAG_MCP_Server):
        mcp_inst.tool(
            self.reranker_init,
            output="model_name_or_path,backend_configs,batch_size,gpu_ids,backend->None",
        )
        mcp_inst.tool(
            self.reranker_rerank,
            output="query_list,passages_list,top_k,query_instruction->rerank_psg",
        )
        mcp_inst.tool(
            self.reranker_rerank_items,
            output="query_list,ret_items,top_k,query_instruction->ret_items",
        )

    def _drop_keys(self, d: Dict[str, Any], banned: List[str]) -> Dict[str, Any]:
        return {k: v for k, v in (d or {}).items() if k not in banned and v is not None}

    @staticmethod
    def _normalize_query_rows(
        query_list: List[str],
        rows: Any,
    ) -> tuple[List[str], List[Any]]:
        normalized_queries = [str(query) for query in list(query_list or [])]
        if rows in (None, ""):
            normalized_rows: List[Any] = []
        elif isinstance(rows, list) and rows and isinstance(rows[0], dict):
            normalized_rows = [rows]
        else:
            normalized_rows = list(rows or [])

        if len(normalized_queries) < len(normalized_rows):
            fill_value = normalized_queries[-1] if normalized_queries else ""
            normalized_queries.extend(
                [fill_value] * (len(normalized_rows) - len(normalized_queries))
            )
        elif len(normalized_rows) < len(normalized_queries):
            normalized_rows.extend([[] for _ in range(len(normalized_queries) - len(normalized_rows))])
        return normalized_queries, normalized_rows

    async def reranker_init(
        self,
        model_name_or_path: str,
        backend_configs: Dict[str, Any],
        batch_size: int,
        gpu_ids: Optional[Union[str, int]] = None,
        backend: str = "sentence_transformers",
    ) -> None:
        self.backend = backend.lower()
        self.batch_size = batch_size
        self.backend_configs = backend_configs

        cfg = self.backend_configs.get(self.backend, {})
        gpu_ids_str = str(gpu_ids) if gpu_ids is not None else ""
        os.environ["CUDA_VISIBLE_DEVICES"] = gpu_ids_str
        self.device_num = len(gpu_ids_str.split(",")) if gpu_ids_str else 1

        if self.backend == "infinity":
            try:
                from infinity_emb import AsyncEngineArray, EngineArgs
            except ImportError as exc:
                err_msg = "infinity_emb is not installed. Please install it with `pip install infinity-emb`."
                app.logger.error(err_msg)
                raise ImportError(err_msg) from exc

            infinity_engine_args = EngineArgs(
                model_name_or_path=model_name_or_path,
                batch_size=self.batch_size,
                **cfg,
            )
            self.model = AsyncEngineArray.from_args([infinity_engine_args])[0]

        elif self.backend == "sentence_transformers":
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                err_msg = (
                    "sentence_transformers is not installed. "
                    "Please install it with `pip install sentence-transformers`."
                )
                app.logger.error(err_msg)
                raise ImportError(err_msg) from exc

            st_params = self._drop_keys(cfg, banned=["sentence_transformers_encode"])
            self.model = CrossEncoder(
                model_name_or_path=model_name_or_path,
                **st_params,
            )

        elif self.backend == "openai":
            model_name = cfg.get("model_name")
            base_url = cfg.get("base_url")
            concurrency = cfg.get("concurrency", 1)

            if not model_name:
                raise ValueError("[openai] model_name is required")
            if not isinstance(base_url, str) or not base_url:
                raise ValueError("[openai] base_url must be a non-empty string")

            self.rerank_url = base_url
            self.model_name = model_name
            self.concurrency = max(1, int(concurrency or 1))
        else:
            raise ValueError(
                f"Unsupported backend: {backend}. "
                "Supported backends: 'infinity', 'sentence_transformers', 'openai'"
            )

    async def _rank_documents(
        self,
        query: str,
        docs: List[str],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        if not docs:
            return []

        top_k = min(int(top_k), len(docs))

        if self.backend == "infinity":
            async with self.model:
                ranking, _ = await self.model.rerank(
                    query=query,
                    docs=docs,
                    top_n=top_k,
                )

            rows = []
            for item in ranking:
                idx = getattr(item, "index", getattr(item, "corpus_id", None))
                if idx is None:
                    continue
                rows.append(
                    {
                        "index": int(idx),
                        "score": float(
                            getattr(item, "relevance_score", getattr(item, "score", 0.0))
                        ),
                        "text": str(getattr(item, "document", docs[int(idx)])),
                    }
                )
            return rows

        if self.backend == "sentence_transformers":
            def _rank_all() -> List[Dict[str, Any]]:
                return self.model.rank(
                    query,
                    docs,
                    top_k=top_k,
                    batch_size=self.batch_size,
                    return_documents=True,
                    show_progress_bar=False,
                )

            raw_ranks = await asyncio.to_thread(_rank_all)
            return [
                {
                    "index": int(rank["corpus_id"]),
                    "score": float(rank.get("score") or 0.0),
                    "text": str(rank.get("text") or docs[int(rank["corpus_id"])]),
                }
                for rank in raw_ranks
                if rank.get("corpus_id") is not None
            ]

        payload = {
            "model": self.model_name,
            "query": query,
            "documents": docs,
            "top_n": top_k,
        }
        semaphore = asyncio.Semaphore(self.concurrency)
        async with aiohttp.ClientSession() as session:
            async with semaphore:
                async with session.post(self.rerank_url, json=payload) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"[{resp.status}] {await resp.text()}")
                    data = await resp.json()

        rows = []
        for item in data.get("results", []) or []:
            idx = item.get("index")
            if idx is None:
                continue
            document = item.get("document")
            if isinstance(document, dict):
                document = document.get("text", "")
            rows.append(
                {
                    "index": int(idx),
                    "score": float(item.get("relevance_score", item.get("score", 0.0)) or 0.0),
                    "text": str(document or docs[int(idx)]),
                }
            )
        return rows

    async def reranker_rerank(
        self,
        query_list: List[str],
        passages_list: List[List[str]],
        top_k: int = 5,
        query_instruction: str = "",
    ) -> Dict[str, List[List[str]]]:
        normalized_queries, normalized_rows = self._normalize_query_rows(
            query_list, passages_list
        )

        reranked_results = []
        formatted_queries = [f"{query_instruction}{query}" for query in normalized_queries]
        for query, docs in tqdm(
            zip(formatted_queries, normalized_rows),
            total=len(formatted_queries),
            desc="Reranking",
        ):
            ranked = await self._rank_documents(query, list(docs or []), top_k)
            reranked_results.append([str(item["text"]) for item in ranked])

        return {"rerank_psg": reranked_results}

    async def reranker_rerank_items(
        self,
        query_list: List[str],
        ret_items: List[List[Dict[str, Any]]],
        top_k: int = 5,
        query_instruction: str = "",
    ) -> Dict[str, List[List[Dict[str, Any]]]]:
        normalized_queries, normalized_rows = self._normalize_query_rows(
            query_list, ret_items
        )

        reranked_rows: List[List[Dict[str, Any]]] = []
        formatted_queries = [f"{query_instruction}{query}" for query in normalized_queries]
        for query, row in tqdm(
            zip(formatted_queries, normalized_rows),
            total=len(formatted_queries),
            desc="Reranking",
        ):
            docs = [str(item.get("content") or "") for item in row]
            ranked = await self._rank_documents(query, docs, top_k)
            reranked_items: List[Dict[str, Any]] = []
            for rank_info in ranked:
                idx = int(rank_info["index"])
                if idx < 0 or idx >= len(row):
                    continue
                item = dict(row[idx])
                item["retrieval_score"] = item.get("score")
                item["rerank_score"] = rank_info["score"]
                item["score"] = rank_info["score"]
                reranked_items.append(item)
            reranked_rows.append(reranked_items)

        return {"ret_items": reranked_rows}


provider = Reranker(app)

if __name__ == "__main__":
    app.run(transport="stdio")
