"""
tutor_platform/tools/embeddings.py — Unified embedding entry point.

BgeSmallEmbedding: ChromaDB-compatible embedding function using sentence-transformers
(BAAI/bge-small-zh-v1.5) loaded in-process.  No external services — no Ollama model-slot
contention, no rkllama NPU, no deterministic-hash fallback.

Single source consumed by:
  - UnifiedLocalProvider._get_embed_fn() → Platform ChromaDB ingestion
  - /api/embed HTTP endpoint → DT ollama adapter (reindex / upload)
"""

import logging
import os

logger = logging.getLogger("tutor_platform.tools.embeddings")

_EMBED_DIM = 512
_DEFAULT_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")


class BgeSmallEmbedding:
    """Sentence-transformers in-process embedding — bge-small-zh-v1.5 loaded once at startup."""

    def __init__(self, model_name: str = "", batch_size: int = 16):
        self.model_name = model_name or _DEFAULT_MODEL_NAME
        self.batch_size = batch_size
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            # Offline-safe: model is pre-cached in the Docker image.
            # Use the snapshot path directly because AutoConfig / HF Hub
            # can't resolve the model name offline (CN network issues).
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

            cache_root = os.environ.get(
                "HF_HOME",
                os.path.join(os.path.expanduser("~"), ".cache", "huggingface"),
            )
            # Try both HF cache layouts: v1 under HF_HOME, v2 under HF_HOME/hub/
            safe_name = self.model_name.replace("/", "--")
            model_dir_name = f"models--{safe_name}"
            for base in (cache_root, os.path.join(cache_root, "hub")):
                snap_dir = os.path.join(base, model_dir_name, "snapshots")
                if os.path.isdir(snap_dir):
                    snapshots = sorted(os.listdir(snap_dir))
                    if snapshots:
                        model_path = os.path.join(snap_dir, snapshots[0])
                        break
            else:
                model_path = self.model_name  # fallback (will fail offline)

            logger.info("Loading bge-small-zh-v1.5 (cold start, offline)... via %s", model_path)
            self._model = SentenceTransformer(
                model_path, trust_remote_code=True,
                local_files_only=True,
            )
            logger.info("BAAI/bge-small-zh-v1.5 ready (%dD)", _EMBED_DIM)

    def __call__(self, input: list[str]) -> list[list[float]]:
        self._ensure_model()
        embeddings = self._model.encode(
            input,
            batch_size=self.batch_size,
            show_progress_bar=False,
            normalize_embeddings=False,
        )
        return embeddings.tolist()


# Backward-compat
RkllamaEmbeddingFunction = BgeSmallEmbedding
M3Embedding = BgeSmallEmbedding
