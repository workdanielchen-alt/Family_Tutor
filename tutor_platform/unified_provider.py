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
        self._embed_fn = None
        logger.info(
            "UnifiedLocalProvider: ollama=%s chroma=%s",
            self._ollama_url,
            self._chroma_dir,
        )

    def _get_embed_fn(self):
        if self._embed_fn is None:
            from tutor_platform.tools.embeddings import RkllamaEmbeddingFunction
            self._embed_fn = RkllamaEmbeddingFunction()
            # Warm up — verify it works
            test = self._embed_fn(["warmup"])
            logger.info("Ollama embedder ready (dim=%d)", len(test[0]))
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
            import chromadb
            from chromadb.config import Settings

            os.makedirs(self._chroma_dir, exist_ok=True)
            client = chromadb.PersistentClient(
                path=self._chroma_dir,
                settings=Settings(anonymized_telemetry=False),
            )
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
            import chromadb
            from chromadb.config import Settings

            os.makedirs(self._chroma_dir, exist_ok=True)
            client = chromadb.PersistentClient(
                path=self._chroma_dir,
                settings=Settings(anonymized_telemetry=False),
            )
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

    async def query(
        self,
        collection_name: str,
        query_texts: list[str],
        n_results: int = 5,
    ) -> list[dict]:
        """Query the vector store for relevant documents."""
        try:
            import chromadb
            from chromadb.config import Settings

            os.makedirs(self._chroma_dir, exist_ok=True)
            client = chromadb.PersistentClient(
                path=self._chroma_dir,
                settings=Settings(anonymized_telemetry=False),
            )
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
                "OCR text extraction for a math tutoring system.\n\n"
                "Rules:\n"
                "1. Only extract text visible in the image — do NOT solve or add content not present\n"
                "2. Chinese text must NOT be wrapped in $ delimiters\n"
                "3. Math formulas, equations, numbers SHOULD be wrapped in $ (inline LaTeX) — "
                "this is formatting, not solving\n"
                "4. Use align* for equation systems; don't add unnecessary parentheses\n"
                "5. Use \\frac{}{} for fractions, \\times for multiplication\n"
                "6. Never add explanations or text not present in the image"
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
                f"{self._ollama_url}/v1/chat/completions",
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
