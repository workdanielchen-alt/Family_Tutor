"""Unified figure data model — single schema for figures from all document sources.

Every extraction path (PDF, Office, standalone images, exam sidecars) produces
``UnifiedFigure`` instances so downstream storage and retrieval are source-agnostic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class UnifiedFigure:
    """A figure extracted from any document type.

    Fields
    ------
    figure_id
        Unique identifier (UUID hex) used as the ChromaDB document ID.
    source_file
        Path of the original document this figure came from.
    page_num
        Page number within the source (0-based).  For standalone images this is 0.
    bbox
        Bounding box ``(x0, y0, x1, y1)`` in PDF points, or ``None`` for
        standalone images / Office embedded images where page coordinates
        are meaningless.
    image_bytes
        The rendered/clipped figure as PNG bytes.  May be ``None`` when the
        figure metadata was reconstructed from a sidecar (no raw image).
    image_path
        On-disk path where the clipped PNG was persisted (if ``save_figures=True``).
    ocr_text
        Any visible text recognised inside the figure region.
    description
        Structured description produced by a multimodal LLM.  The schema
        varies by figure type (see ``_FIGURE_PROMPTS`` in **block_ocr.py**):
        geometry → ``{figure_type, vertices, given, to_find_or_prove, description}``
        function_graph → ``{function_hint, x_range, y_range, special_points, description}``
        table → Markdown table string
        illustration → ``{type, elements, description}``
    fig_type
        Canonical figure type: ``geometry`` | ``function_graph`` | ``table``
        | ``illustration`` | ``unknown``.
    caption
        Figure caption extracted from surrounding text (e.g. "图3-1 三角形分类").
    referring_chunks
        IDs of text chunks that reference this figure (e.g. via "如图X" patterns).
        Populated during the chunking phase.
    """

    figure_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    source_file: str = ""
    page_num: int = 0
    bbox: tuple[float, float, float, float] | None = None
    image_bytes: bytes | None = None
    image_path: str | None = None
    ocr_text: str = ""
    description: dict | None = None
    fig_type: str = "unknown"
    caption: str = ""
    referring_chunks: list[str] = field(default_factory=list)

    @property
    def description_text(self) -> str:
        """Serialize the description to a plain-text string for text embedding.

        Falls back to ``ocr_text`` when no structured description exists.
        """
        if self.description:
            return _serialize_description(self.description, self.fig_type)
        if self.ocr_text:
            return f"[{self.fig_type}] {self.ocr_text}"
        return ""

    @property
    def is_empty(self) -> bool:
        """Return True when the figure carries no usable content."""
        return not self.ocr_text and not self.description and not self.caption


def _serialize_description(desc: dict, fig_type: str) -> str:
    """Turn a structured description dict into a human-readable string."""
    parts: list[str] = [f"[{fig_type}]"]

    if fig_type == "geometry":
        vertices = desc.get("vertices", [])
        if vertices:
            parts.append(f"顶点: {'/'.join(vertices)}")
        given = desc.get("given", [])
        if given:
            parts.append(f"已知: {'; '.join(given)}")
        to_find = desc.get("to_find_or_prove", "")
        if to_find:
            parts.append(f"求证/求: {to_find}")

    elif fig_type == "function_graph":
        hint = desc.get("function_hint", "")
        if hint:
            parts.append(f"函数类型: {hint}")
        xr = desc.get("x_range", [])
        yr = desc.get("y_range", [])
        if xr:
            parts.append(f"x范围: [{xr[0]}, {xr[1]}]")
        if yr:
            parts.append(f"y范围: [{yr[0]}, {yr[1]}]")
        sp = desc.get("special_points", [])
        if sp:
            labels = [p.get("label", "") for p in sp]
            parts.append(f"关键点: {', '.join(filter(None, labels))}")

    elif fig_type == "table":
        raw = desc.get("raw", "")
        if raw:
            parts.append(raw)

    else:  # illustration / unknown
        desc_text = desc.get("description") or desc.get("raw", "")
        if isinstance(desc_text, str):
            parts.append(desc_text)
        elements = desc.get("elements", [])
        if elements:
            parts.append(f"元素: {'; '.join(str(e) for e in elements[:8])}")

    # Append the common Chinese human-friendly desc if present
    human_desc = None
    if isinstance(desc, dict):
        human_desc = desc.get("description")
    if human_desc and isinstance(human_desc, str) and human_desc not in parts:
        parts.append(human_desc)

    return " ".join(parts)
