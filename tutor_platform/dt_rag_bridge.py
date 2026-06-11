"""DT LlamaIndex RAG bridge — queries DT knowledge bases directly from platform.

The platform shares the deeptutor knowledge_bases volume at /data/knowledge_bases
and has llama-index installed.  This module replicates the essential index-loading
and retrieval logic from vendor/deeptutor/deeptutor/services/rag/pipelines/llamaindex/
so the teaching pipeline can query DT's [PDF Image] nodes + original text chunks
without going through the DT HTTP API (which has no search endpoint).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Optional

from llama_index.core import (
    Settings,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.indices.query.schema import QueryBundle

try:
    from llama_index.retrievers.bm25 import BM25Retriever
except ImportError:
    BM25Retriever = None  # type: ignore[assignment]

from tutor_platform.tools.embeddings import BgeSmallEmbedding

from llama_index.core.embeddings import BaseEmbedding

logger = logging.getLogger(__name__)


class _BgeEmbedAdapter(BaseEmbedding):
    """Minimal LlamaIndex-compatible embedding wrapper around BgeSmallEmbedding."""

    _fn: Any

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from tutor_platform.tools.embeddings import BgeSmallEmbedding
        self._fn = BgeSmallEmbedding()
        self.model_name = "bge-small-zh-v1.5"

    @classmethod
    def class_name(cls) -> str:
        return "BgeEmbedAdapter"

    def _get_text_embedding(self, text: str) -> list[float]:
        return list(self._fn([text])[0])

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._fn(texts)]

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_text_embedding(query)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._get_text_embedding(query)


_embed_adapter: _BgeEmbedAdapter | None = None
_index_cache: dict[str, Any] = {}  # kb_name → loaded index


def _get_embed_model() -> _BgeEmbedAdapter:
    global _embed_adapter
    if _embed_adapter is None:
        _embed_adapter = _BgeEmbedAdapter()
    return _embed_adapter


def _configure_settings() -> None:
    Settings.embed_model = _get_embed_model()
    Settings.chunk_size = 1024
    Settings.chunk_overlap = 200
    Settings.llm = None  # prevent auto-detect of OpenAI
    Settings.callback_manager = None


async def retrieve_from_dt_index(
    query: str,
    kb_name: str = "初中教材",
    *,
    top_k: int = 5,
) -> str:
    """Query DT's LlamaIndex vector+BM25 index and return concatenated text.

    Returns empty string if the index doesn't exist or the query fails.
    """
    storage_dir = Path("/data/knowledge_bases") / kb_name / "version-1"
    if not (storage_dir / "docstore.json").exists():
        logger.warning("DT index not found: %s", storage_dir)
        return ""

    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: _retrieve_sync(str(storage_dir), query, top_k),
        )
    except Exception as exc:
        logger.warning("DT index query failed for '%s': %s", kb_name, exc)
        return ""


def _retrieve_sync(storage_dir: str, query: str, top_k: int) -> str:
    _configure_settings()

    # Cache the loaded index — loading from disk costs ~7s
    kb_name = Path(storage_dir).parent.name
    if kb_name not in _index_cache:
        storage_context = StorageContext.from_defaults(persist_dir=storage_dir)
        _index_cache[kb_name] = load_index_from_storage(storage_context)
        logger.info("DT index cached: %s", kb_name)
    index = _index_cache[kb_name]

    # Try hybrid (BM25 + vector), fall back to vector-only
    bm25_dir = Path(storage_dir) / "bm25_retriever"
    if BM25Retriever is not None and (bm25_dir / "corpus.jsonl").exists():
        from llama_index.core.retrievers.fusion_retriever import FUSION_MODES

        vector_retriever = index.as_retriever(similarity_top_k=top_k * 2)
        bm25 = BM25Retriever.from_defaults(
            index=index,
            similarity_top_k=top_k * 2,
        )
        retriever = QueryFusionRetriever(
            [vector_retriever, bm25],
            llm=None,
            mode=FUSION_MODES.RECIPROCAL_RANK,
            similarity_top_k=top_k,
            num_queries=1,
            use_async=False,
        )
    else:
        retriever = index.as_retriever(similarity_top_k=top_k)

    nodes = retriever.retrieve(query)
    if not nodes:
        return ""

    parts: list[str] = []
    for i, node in enumerate(nodes, 1):
        text = node.node.text if hasattr(node, "node") else node.text
        meta = node.node.metadata if hasattr(node, "node") else node.metadata
        file_name = meta.get("file_name", "") if meta else ""
        page = meta.get("page_number", "") if meta else ""
        source = f"{file_name}" + (f" p.{page}" if page else "")
        parts.append(f"**[来源 {i}: {source}]**\n{text.strip()[:600]}")
    return "\n\n".join(parts)
