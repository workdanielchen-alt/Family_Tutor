"""Unified provider: LLM, OCR, vision, and vector store abstraction.

Provides a singleton provider instance that wraps Ollama/DeepSeek APIs,
ChromaDB vector store, and OCR capabilities.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_provider_instance: UnifiedLocalProvider | None = None


class UnifiedLocalProvider:
    """Unified provider for LLM, OCR, vision, and vector store operations."""

    def __init__(self):
        self._ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        self._deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        self._chroma_dir = os.getenv("CHROMA_PERSIST_DIR", "/data/chromadb")
        self._client = httpx.AsyncClient(timeout=120)
        self._ocr_model = os.getenv("OLLAMA_OCR_MODEL", "openbmb/minicpm-v4.6:q4_K_M")
        self._ocr_url = os.getenv("OCR_URL", "").rstrip("/") or self._ollama_url
        self._embed_fn = None
        # ChromaDB client 缓存 — ChromaDB 1.x Rust API 不允许重复创建 PersistentClient
        self._chroma_client = None
        logger.info(
            "UnifiedLocalProvider: ollama=%s chroma=%s",
            self._ollama_url,
            self._chroma_dir,
        )

    def _get_chroma_client(self):
        """获取（并缓存）ChromaDB PersistentClient 单例。

        ChromaDB 1.x 的 Rust 引擎将配置固化在 SQLite 中，重复调用
        PersistentClient() 会导致 "different settings" 错误。
        缓存后所有请求共享同一个客户端实例。

        必须传入 Settings(anonymized_telemetry=False) 以匹配
        provider_api.py 中其他 PersistentClient() 调用（如 api_kb_search），
        否则第一个写入此设置的调用会锁死 SQLite，后续用默认设置
        （anonymized_telemetry=True）的调用被拒绝。
        """
        if self._chroma_client is None:
            import chromadb
            from chromadb.config import Settings
            os.makedirs(self._chroma_dir, exist_ok=True)
            self._chroma_client = chromadb.PersistentClient(
                path=self._chroma_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            logger.info("ChromaDB client created (path=%s)", self._chroma_dir)
        return self._chroma_client

    def _get_embed_fn(self):
        if self._embed_fn is None:
            from tutor_platform.tools.embeddings import BgeSmallEmbedding
            self._embed_fn = BgeSmallEmbedding()
            # Warm up — verify it works
            test = self._embed_fn(["warmup"])
            logger.info("Embedder ready (dim=%d)", len(test[0]))
        return self._embed_fn

    async def add_documents(
        self,
        kb_name: str,
        documents: list[str],
        metadatas: list[dict] | None = None,
        ids: list[str] | None = None,
    ) -> dict:
        """Batch-add chunked documents to the knowledge base."""
        if not documents:
            return {"ok": True, "count": 0}
        try:
            client = self._get_chroma_client()
            collection = client.get_or_create_collection(name=kb_name)

            embed_fn = self._get_embed_fn()
            loop = asyncio.get_running_loop()
            embeddings = await loop.run_in_executor(
                None, lambda: embed_fn(documents)
            )

            collection.add(
                embeddings=embeddings,
                documents=documents,
                ids=ids or [f"chunk_{i}" for i in range(len(documents))],
                metadatas=metadatas,
            )
            return {"ok": True, "count": len(documents)}
        except Exception as e:
            logger.warning("add_documents failed (non-fatal): %s", e)
            return {"ok": False, "error": str(e)}

    async def ingest_text(
        self,
        content: str,
        kb_name: str,
        filename: str = "",
        source: str = "",
        trace_id: str = "",
    ) -> dict:
        """Ingest text content into the knowledge base."""
        try:
            client = self._get_chroma_client()
            collection = client.get_or_create_collection(name=kb_name)

            doc_id = f"{filename or 'text'}_{trace_id or id(content)}"
            embed_fn = self._get_embed_fn()
            loop = asyncio.get_running_loop()
            embeddings = await loop.run_in_executor(
                None, lambda: embed_fn([content])
            )

            if embeddings is not None and len(embeddings) > 0 and embeddings[0] is not None:
                collection.add(
                    embeddings=embeddings,
                    documents=[content],
                    ids=[doc_id],
                    metadatas=[{"filename": filename, "source": source}],
                )
            return {"ok": True, "doc_id": doc_id}
        except Exception as e:
            logger.warning("Ingest text failed (non-fatal): %s", e)
            return {"ok": False, "error": str(e)}

    async def add_figures(
        self,
        kb_name: str,
        figures: list[dict],
    ) -> dict:
        """Store figure descriptions in a dedicated ``{kb_name}_figures`` collection.

        Each figure is stored with its ``description_text`` as the document
        (embedded via the text embedder) and metadata carrying ``figure_id``,
        ``fig_type``, ``source_file``, ``page_num``, and ``bbox``.

        Returns ``{"ok": True, "count": N}`` on success.
        """
        if not figures:
            return {"ok": True, "count": 0}

        try:
            client = self._get_chroma_client()
            _safe_fig_name = _sanitize_collection_name(f"{kb_name}_figures")
            fig_collection = client.get_or_create_collection(
                name=_safe_fig_name,
            )

            docs: list[str] = []
            ids: list[str] = []
            metadatas: list[dict] = []
            for fig in figures:
                desc_text = fig.get("description_text") or fig.get("ocr_text", "")
                if not desc_text:
                    continue
                docs.append(desc_text)
                ids.append(fig.get("figure_id", ""))
                metadatas.append({
                    "figure_id": fig.get("figure_id", ""),
                    "fig_type": fig.get("fig_type", "unknown"),
                    "source_file": fig.get("source_file", ""),
                    "image_path": fig.get("image_path", ""),
                    "page_num": str(fig.get("page_num", 0)),
                    "caption": fig.get("caption", ""),
                })

            if not docs:
                return {"ok": True, "count": 0}

            embed_fn = self._get_embed_fn()
            loop = asyncio.get_running_loop()
            embeddings = await loop.run_in_executor(
                None, lambda: embed_fn(docs),
            )

            fig_collection.add(
                embeddings=embeddings,
                documents=docs,
                ids=ids,
                metadatas=metadatas,
            )
            logger.info("Added %d figures to %s_figures", len(docs), kb_name)
            return {"ok": True, "count": len(docs)}
        except Exception as e:
            logger.warning("add_figures failed (non-fatal): %s", e)
            return {"ok": False, "error": str(e)}

    async def query(
        self,
        collection_name: str,
        query_texts: list[str],
        n_results: int = 5,
        include_figures: bool = False,
    ) -> list[dict]:
        """Query the vector store for relevant documents."""
        try:
            client = self._get_chroma_client()
            collection = client.get_collection(name=collection_name)

            embed_fn = self._get_embed_fn()
            loop = asyncio.get_running_loop()
            query_embs = await loop.run_in_executor(
                None, lambda: embed_fn(query_texts)
            )
            if query_embs is None or len(query_embs) == 0 or query_embs[0] is None:
                return []

            results = collection.query(
                query_embeddings=query_embs,
                n_results=n_results,
            )
            docs = []
            distances_list = results.get("distances", [[]])[0] or []
            metadatas_list = results.get("metadatas", [[]])[0] or []
            for i, doc in enumerate(results.get("documents", [[]])[0]):
                meta = metadatas_list[i] if i < len(metadatas_list) else {}
                dist = float(distances_list[i]) if i < len(distances_list) else 1.0
                docs.append({"content": doc, "metadata": meta, "distance": dist})

            # ── Parallel figure search ──
            if include_figures and docs:
                try:
                    fig_collection = client.get_collection(
                        name=_sanitize_collection_name(f"{collection_name}_figures"),
                    )
                    fig_results = fig_collection.query(
                        query_embeddings=query_embs,
                        n_results=max(3, n_results // 2),
                    )
                    fig_docs = []
                    fig_distances = fig_results.get("distances", [[]])[0] or []
                    fig_metadatas = fig_results.get("metadatas", [[]])[0] or []
                    for i, fig_doc in enumerate(fig_results.get("documents", [[]])[0]):
                        meta = fig_metadatas[i] if i < len(fig_metadatas) else {}
                        dist = float(fig_distances[i]) if i < len(fig_distances) else 1.0
                        fig_docs.append({
                            "content": fig_doc,
                            "metadata": meta,
                            "distance": dist,
                            "type": "figure",
                        })
                    # Merge figures into main result
                    for d in docs:
                        d["figures"] = [
                            f for f in fig_docs
                            if f["distance"] < 0.8
                        ][:3]
                except Exception:
                    pass  # No figure collection exists yet = no figures to return

            return docs
        except Exception as e:
            logger.warning("Vector query failed (non-fatal): %s", e)
            return []

    async def ocr(
        self,
        image_data: str,
        language: str = "zh",
        return_formulas: bool = True,
        return_layout: bool = True,
        tool_name: str = "",
    ) -> str:
        """OCR an image using the configured multimodal LLM."""
        try:
            img_bytes = base64.b64decode(image_data)
            img_b64 = base64.b64encode(img_bytes).decode("ascii")
            prompt = (
                "Read the text in this image. "
                "Output only the visible text content. "
                "Wrap math formulas in $, e.g. $x^2 + 2x + 1 = 0$."
            )
            payload = {
                "model": self._ocr_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                            },
                        ],
                    }
                ],
                "temperature": 0,
                "stream": False,
            }
            resp = await self._client.post(
                f"{self._ocr_url}/v1/chat/completions",
                json=payload,
            )
            if resp.status_code != 200:
                logger.warning("OCR failed: HTTP %d", resp.status_code)
                return ""
            data = resp.json()
            return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        except Exception as e:
            logger.warning("OCR failed: %s", e)
            return ""

    async def vision(
        self,
        image_data: str,
        question: str = "",
        tool_name: str = "",
    ) -> str:
        """Vision QA using multimodal LLM."""
        try:
            prompt = question or "Describe what you see in this image."
            payload = {
                "model": self._ocr_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_data},
                            },
                        ],
                    }
                ],
                "stream": False,
            }
            resp = await self._client.post(
                f"{self._ollama_url}/v1/chat/completions",
                json=payload,
            )
            if resp.status_code != 200:
                logger.warning("Vision failed: HTTP %d", resp.status_code)
                return ""
            data = resp.json()
            return (data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        except Exception as e:
            logger.warning("Vision failed: %s", e)
            return ""


def _sanitize_collection_name(name: str) -> str:
    """Convert any KB name to a ChromaDB-valid collection name.

    ChromaDB requires: 3-512 chars, [a-zA-Z0-9._-], start/end with [a-zA-Z0-9].
    """
    import hashlib, base64

    if not name:
        return "default_figures"
    # Already valid ASCII → keep as-is
    if all(c.isascii() and (c.isalnum() or c in "._-") for c in name) and name[0].isalnum():
        return name
    # Non-ASCII: use hash suffix
    safe = "".join(c if c.isascii() and (c.isalnum() or c in "._-") else "_" for c in name)
    safe = safe.strip("_")[:48] or "kb"
    digest = hashlib.sha256(name.encode()).digest()[:8]
    suffix = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{safe}_{suffix}"


def get_provider_instance() -> UnifiedLocalProvider:
    """Get or create the singleton provider instance."""
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = UnifiedLocalProvider()
    return _provider_instance


def reset_provider_instance() -> None:
    """Reset the provider singleton (forces re-initialization on next access)."""
    global _provider_instance
    _provider_instance = None
