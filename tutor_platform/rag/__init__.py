"""RAG document preprocessing pipeline — lazy imports to avoid circular deeptutor dependency."""


def __getattr__(name):
    """Lazy import shim — avoids importing deeptutor on module load.

    This is required because the ``platform`` container mounts ``/tutor_platform``
    but does not have ``deeptutor`` installed.  Modules are imported only when
    explicitly accessed.
    """
    if name == "PipelineConfig":
        from tutor_platform.rag.config import PipelineConfig as _M
        return _M
    if name == "ProcessingContext":
        from tutor_platform.rag.context import ProcessingContext as _M
        return _M
    if name == "RagDocumentPipeline":
        from tutor_platform.rag.pipeline import RagDocumentPipeline as _M
        return _M
    if name == "UnifiedDocumentPipeline":
        from tutor_platform.rag.unified_pipeline import UnifiedDocumentPipeline as _M
        return _M
    raise AttributeError(f"module 'tutor_platform.rag' has no attribute '{name}'")


__all__ = [
    "PipelineConfig",
    "ProcessingContext",
    "RagDocumentPipeline",
    "UnifiedDocumentPipeline",
]
