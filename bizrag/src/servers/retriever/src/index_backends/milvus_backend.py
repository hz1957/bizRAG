from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from urllib.parse import urlparse
from tqdm import tqdm

from .base import BaseIndexBackend

try:
    from pymilvus import MilvusClient, DataType
except ImportError:
    MilvusClient = None
    DataType = None


class MilvusIndexBackend(BaseIndexBackend):
    """Milvus-based index backend for vector similarity search."""

    def __init__(
        self,
        contents: Sequence[str],
        config: Optional[dict[str, Any]],
        logger,
        **_: Any,
    ) -> None:
        """Initialize Milvus index backend.

        Args:
            contents: Sequence of document contents (not used for Milvus)
            config: Configuration dictionary
            logger: Logger instance
        """
        if MilvusClient is None:
            err_msg = (
                "pymilvus is not installed. Install it with `pip install pymilvus` "
                "or include it in the retriever extras."
            )
            logger.error(err_msg)
            raise ImportError(err_msg)

        super().__init__(contents=[], config=config, logger=logger)

        self.uri = str(self._resolve_index_path(self.config.get("uri")))
        self.token = self.config.get("token")
        self.collection_name = self.config.get("collection_name")
        self.collection_display_name = self.config.get("collection_display_name")

        self.id_field: str = str(self.config.get("id_field_name", "id"))
        self.vector_field: str = str(self.config.get("vector_field_name", "vector"))
        self.text_field: str = str(self.config.get("text_field_name", "contents"))

        self.metric_type: str = str(self.config.get("metric_type", "IP"))
        self.index_params: dict[str, Any] = dict(self.config.get("index_params", {}))
        self.search_params: dict[str, Any] = dict(self.config.get("search_params", {}))

        self.id_max_length = int(self.config.get("id_max_length", 64))
        self.text_max_length = int(self.config.get("text_max_length", 60000))

        self.client = None

    @staticmethod
    def _validate_collection_name(name: str) -> bool:
        """Validate collection name to prevent injection attacks.
        
        Args:
            name: Collection name to validate
            
        Returns:
            True if valid, False otherwise
        """
        if not name or not isinstance(name, str):
            return False
        # Only allow alphanumeric characters, underscores, and hyphens
        # Maximum length check
        if len(name) > 255:
            return False
        # Pattern: alphanumeric, underscore, hyphen only
        return bool(re.match(r'^[a-zA-Z0-9_-]+$', name))

    @staticmethod
    def _validate_field_name(name: str) -> bool:
        return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""))

    @staticmethod
    def _format_filter_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return json.dumps(str(value), ensure_ascii=False)

    def _build_filter_expression(self, filters: Optional[Dict[str, Any]]) -> Optional[str]:
        if not filters:
            return None

        clauses: List[str] = []
        for field, raw_value in filters.items():
            if raw_value is None or raw_value == "":
                continue
            if not self._validate_field_name(field):
                raise ValueError(f"[milvus] Invalid filter field: '{field}'")

            values = raw_value if isinstance(raw_value, list) else [raw_value]
            values = [v for v in values if v is not None and v != ""]
            if not values:
                continue

            if len(values) == 1:
                clauses.append(f"{field} == {self._format_filter_value(values[0])}")
            else:
                expr_values = ", ".join(self._format_filter_value(v) for v in values)
                clauses.append(f"{field} in [{expr_values}]")

        return " and ".join(clauses) if clauses else None

    def _resolve_index_path(self, index_path: Optional[str]) -> str:
        """Resolve Milvus URI from config.

        Args:
            index_path: URI string from config

        Returns:
            Resolved URI string

        Raises:
            ValueError: If URI is not provided
        """
        if not index_path:
            raise ValueError("[milvus] 'uri' (index_path) is required in config.")

        parsed = urlparse(str(index_path))
        if parsed.scheme in {"http", "https", "tcp"}:
            return str(index_path)

        dir_path = os.path.dirname(index_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        return str(index_path)

    def _client_connect(self) -> MilvusClient:
        """Connect to Milvus client (lazy initialization).

        Returns:
            MilvusClient instance
        """
        if self.client is None:
            if self.token:
                self.client = MilvusClient(uri=self.uri, token=self.token)
            else:
                self.client = MilvusClient(self.uri)
        return self.client

    def _ensure_collection(
        self,
        dim: int,
        overwrite: bool,
        collection_name: str,
    ) -> None:
        """Ensure collection exists, create if needed.

        Args:
            dim: Vector dimension
            overwrite: Whether to drop existing collection
            collection_name: Name of collection

        Raises:
            RuntimeError: If collection creation fails
            ValueError: If collection name is invalid
        """
        # Validate collection name to prevent injection
        if not self._validate_collection_name(collection_name):
            raise ValueError(
                f"[milvus] Invalid collection name: '{collection_name}'. "
                "Collection names must contain only alphanumeric characters, underscores, and hyphens."
            )
        
        client = self._client_connect()

        has_collection = client.has_collection(collection_name)

        if overwrite and has_collection:
            try:
                client.drop_collection(collection_name)
                self.logger.info(
                    f"[milvus] Dropped existing collection '{collection_name}'."
                )
                has_collection = False
            except Exception as e:
                self.logger.warning(f"[milvus] Failed to drop collection: {e}")

        if has_collection:
            return

        self.logger.info(f"[milvus] Creating Demo Schema for '{collection_name}'...")

        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=True,
            description=f"UltraRAG KB | display_name={self.collection_display_name or collection_name}",
        )

        schema.add_field(
            field_name=self.id_field,
            datatype=DataType.VARCHAR,
            max_length=self.id_max_length,
            is_primary=True,
        )

        schema.add_field(
            field_name=self.vector_field, datatype=DataType.FLOAT_VECTOR, dim=dim
        )

        schema.add_field(
            field_name=self.text_field,
            datatype=DataType.VARCHAR,
            max_length=self.text_max_length,
            description="Original document content",
        )

        index_params = client.prepare_index_params()

        index_params.add_index(
            field_name=self.vector_field,
            metric_type=self.metric_type,
            index_type=self.index_params.get("index_type", "AUTOINDEX"),
            params=self.index_params.get("params", {}),
        )

        try:
            client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
            )
            self.logger.info(
                f"[milvus] Successfully created collection '{collection_name}'."
            )

        except Exception as e:
            self.logger.error(f"[milvus] Failed to create collection: {e}")
            raise RuntimeError(f"Milvus create collection failed: {e}")

    def load_index(self) -> None:
        """Connect to Milvus (index is stored in database, not loaded from file)."""
        self._client_connect()

    def drop_collection(self, collection_name: Optional[str] = None) -> None:
        target_collection = collection_name or self.collection_name
        if not target_collection:
            raise ValueError("[milvus] collection_name is required to drop collection")
        if not self._validate_collection_name(target_collection):
            raise ValueError(
                f"[milvus] Invalid collection name: '{target_collection}'. "
                "Collection names must contain only alphanumeric characters, underscores, and hyphens."
            )

        client = self._client_connect()
        if not client.has_collection(target_collection):
            self.logger.info(
                "[milvus] Collection '%s' does not exist, skip drop.",
                target_collection,
            )
            return

        client.drop_collection(target_collection)
        self.logger.info("[milvus] Dropped collection '%s'.", target_collection)

    def build_index(
        self,
        *,
        embeddings: np.ndarray,
        ids: np.ndarray,
        overwrite: bool = False,
        **kwargs: Any,
    ) -> None:
        """Build Milvus index by inserting vectors into collection.

        Args:
            embeddings: 2D numpy array of embeddings
            ids: 1D numpy array of vector IDs
            overwrite: Whether to drop existing collection
            **kwargs: Additional parameters (collection_name, contents, metadatas)

        Raises:
            ValueError: If embeddings/ids have invalid shapes or contents missing
        """

        client = self._client_connect()
        target_collection = kwargs.get("collection_name", self.collection_name)
        
        # Validate collection name to prevent injection
        if target_collection and not self._validate_collection_name(target_collection):
            raise ValueError(
                f"[milvus] Invalid collection name: '{target_collection}'. "
                "Collection names must contain only alphanumeric characters, underscores, and hyphens."
            )

        passed_contents = kwargs.get("contents", None)
        passed_metadatas = kwargs.get("metadatas", None)

        if not passed_contents:
            raise ValueError(
                "[milvus] 'contents' is required for build_index in Demo mode."
            )

        embeddings = np.asarray(embeddings, dtype=np.float32, order="C")
        ids = np.array(ids).astype(str)

        if embeddings.ndim != 2:
            raise ValueError("[milvus] embeddings must be a 2-D array.")
        if ids.shape[0] != embeddings.shape[0]:
            raise ValueError("[milvus] ids must align with embeddings.")

        dim = int(embeddings.shape[1])

        self._ensure_collection(
            dim=dim,
            overwrite=overwrite,
            collection_name=target_collection,
        )

        total = embeddings.shape[0]
        self.logger.info(
            f"[milvus] Inserting {total} vectors into '{target_collection}'."
        )

        data = []
        for i, (doc_id, vec, text) in enumerate(zip(ids, embeddings, passed_contents)):
            row = {self.id_field: doc_id, self.vector_field: vec, self.text_field: text}
            if passed_metadatas:
                if i < len(passed_metadatas):
                    meta = passed_metadatas[i]
                    if isinstance(meta, dict):
                        safe_meta = {
                            k: v
                            for k, v in meta.items()
                            if k not in {self.id_field, self.vector_field, self.text_field}
                        }
                        row.update(safe_meta)
            data.append(row)

        chunk_size = int(self.config.get("index_chunk_size", 1000))

        with tqdm(total=total, desc="[milvus] Uploading", unit="vec") as pbar:
            for start in range(0, total, chunk_size):
                end = min(start + chunk_size, total)
                batch_data = data[start:end]

                res = client.insert(collection_name=target_collection, data=batch_data)
                pbar.update(end - start)
        try:
            client.flush(target_collection)
        except Exception as e:
            self.logger.warning(
                f"[milvus] Flush warning (indexing might be delayed): {e}"
            )
        try:
            client.load_collection(target_collection)
        except Exception:
            pass

        self.logger.info("[milvus] Index ready on collection '%s'.", target_collection)

    def search(
        self,
        query_embeddings: np.ndarray,
        top_k: int,
        **kwargs: Any,
    ) -> List[List[str]]:
        """Search for similar passages using Milvus index.

        Args:
            query_embeddings: 2D numpy array of query embeddings
            top_k: Number of top results to return per query
            **kwargs: Additional parameters (collection_name)

        Returns:
            List of lists, where each inner list contains top_k passage strings

        Raises:
            ValueError: If query_embeddings has invalid shape
            RuntimeError: If search fails
        """

        payload = self.search_payload(query_embeddings, top_k, **kwargs)
        results: List[List[str]] = []
        for row in payload:
            results.append([str(hit.get("content") or "") for hit in row])
        return results

    def search_payload(
        self,
        query_embeddings: np.ndarray,
        top_k: int,
        **kwargs: Any,
    ) -> List[List[Dict[str, Any]]]:
        client = self._client_connect()
        target_collection = kwargs.get("collection_name", self.collection_name)

        if target_collection and not self._validate_collection_name(target_collection):
            raise ValueError(
                f"[milvus] Invalid collection name: '{target_collection}'. "
                "Collection names must contain only alphanumeric characters, underscores, and hyphens."
            )

        query_embeddings = np.asarray(query_embeddings, dtype=np.float32, order="C")
        if query_embeddings.ndim != 2:
            raise ValueError("[milvus] query embeddings must be 2-D.")

        output_fields = kwargs.get("output_fields") or [
            self.text_field,
            "doc_id",
            "title",
            "file_name",
            "source_type",
            "sheet_name",
            "row_index",
            "kb_id",
            "doc_version",
            "source_uri",
        ]
        output_fields = list(dict.fromkeys(output_fields))
        if self.text_field not in output_fields:
            output_fields.insert(0, self.text_field)

        filter_expr = kwargs.get("filter_expr")
        if filter_expr is None:
            filter_expr = self._build_filter_expression(kwargs.get("filters"))

        search_kwargs: Dict[str, Any] = {
            "collection_name": target_collection,
            "data": query_embeddings,
            "limit": int(top_k),
            "search_params": self.search_params,
            "output_fields": output_fields,
            "consistency_level": "Bounded",
        }
        if filter_expr:
            search_kwargs["filter"] = filter_expr

        try:
            res = client.search(**search_kwargs)
        except Exception as exc:
            if output_fields != [self.text_field]:
                fallback_kwargs = dict(search_kwargs)
                fallback_kwargs["output_fields"] = [self.text_field]
                try:
                    self.logger.warning(
                        "[milvus] Search with metadata fields failed on '%s': %s. "
                        "Retrying with content-only output.",
                        target_collection,
                        exc,
                    )
                    res = client.search(**fallback_kwargs)
                    output_fields = [self.text_field]
                except Exception as fallback_exc:
                    raise RuntimeError(
                        f"[milvus] Search failed on '{target_collection}': {fallback_exc}"
                    ) from fallback_exc
            else:
                raise RuntimeError(
                    f"[milvus] Search failed on '{target_collection}': {exc}"
                ) from exc

        rows: List[List[Dict[str, Any]]] = []
        for hits in res:
            row: List[Dict[str, Any]] = []
            for hit in hits:
                entity = hit.get("entity", {}) if isinstance(hit, dict) else {}
                if not isinstance(entity, dict):
                    entity = {}

                content = entity.get(self.text_field)
                if content is None and isinstance(hit, dict):
                    content = hit.get(self.text_field)

                item: Dict[str, Any] = {
                    "content": str(content) if content is not None else "",
                    "score": float(hit.get("distance", hit.get("score", 0.0))),
                }

                primary_id = hit.get("id") if isinstance(hit, dict) else None
                if primary_id is not None:
                    item["vector_id"] = str(primary_id)

                for field in output_fields:
                    if field == self.text_field:
                        continue
                    value = entity.get(field)
                    if value is not None:
                        item[field] = value

                row.append(item)
            rows.append(row)

        return rows
