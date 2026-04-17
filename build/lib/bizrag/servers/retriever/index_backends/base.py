from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional, Sequence

import numpy as np


class BaseIndexBackend(abc.ABC):
    """Abstract base class for index backends.

    This class defines the interface that all index backends must implement
    for vector similarity search operations.
    """

    def __init__(
        self,
        contents: Sequence[str],
        config: Optional[Dict[str, Any]],
        logger,
        **_: Any,
    ) -> None:
        """Initialize base index backend.

        Args:
            contents: Sequence of document contents
            config: Optional configuration dictionary
            logger: Logger instance for logging
        """
        self.contents: List[str] = list(contents)
        self.config: Dict[str, Any] = dict(config or {})
        self.logger = logger

    @abc.abstractmethod
    def load_index(self, *, index_path: Optional[str] = None) -> None:
        """Load existing index from disk or database.

        Args:
            index_path: Optional path to index file (backend-specific)
        """
        ...

    @abc.abstractmethod
    def build_index(
        self,
        *,
        embeddings: np.ndarray,
        ids: np.ndarray,
        index_path: Optional[str] = None,
        overwrite: bool = False,
        index_chunk_size: int = 50000,
        **kwargs: Any,
    ) -> None:
        """Build index from embeddings.

        Args:
            embeddings: 2D numpy array of embeddings (n_vectors, dim)
            ids: 1D numpy array of vector IDs
            index_path: Optional path to save index
            overwrite: Whether to overwrite existing index
            index_chunk_size: Chunk size for batch indexing
            **kwargs: Additional backend-specific parameters
        """
        ...

    @abc.abstractmethod
    def search(
        self,
        query_embeddings: np.ndarray,
        top_k: int,
        **kwargs: Any,
    ) -> List[List[str]]:
        """Search for similar passages.

        Args:
            query_embeddings: 2D numpy array of query embeddings (n_queries, dim)
            top_k: Number of top results to return per query
            **kwargs: Additional backend-specific parameters

        Returns:
            List of lists, where each inner list contains top_k passage strings
        """
        ...

    def close(self) -> None:
        """Optional hook for releasing resources."""
        return None

    def drop_collection(self, collection_name: Optional[str] = None) -> None:
        """Optional hook for dropping a logical collection in stateful backends."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement drop_collection"
        )

    def delete_by_filter(
        self,
        *,
        collection_name: Optional[str] = None,
        filter_expr: str,
    ) -> int:
        """Optional hook for deleting indexed rows by backend-specific filter."""
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement delete_by_filter"
        )

    def search_payload(
        self,
        query_embeddings: np.ndarray,
        top_k: int,
        **kwargs: Any,
    ) -> List[List[Dict[str, Any]]]:
        """Structured search result with metadata.

        Backends that do not support metadata can fall back to content-only results.
        """
        hits = self.search(query_embeddings, top_k, **kwargs)
        payload: List[List[Dict[str, Any]]] = []
        for row in hits:
            payload.append(
                [
                    {
                        "content": content,
                        "score": None,
                    }
                    for content in row
                ]
            )
        return payload
