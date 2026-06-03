# DeepTutor 统一文档处理架构

> 版本: 1.0 | 最后更新: 2026-06-04

## 目录

1. [架构概览](#1-架构概览)
2. [文档分类体系](#2-文档分类体系)
3. [统一入口 — UnifiedDocumentPipeline](#3-统一入口--unifieddocumentpipeline)
4. [各类型文档处理路径](#4-各类型文档处理路径)
5. [试卷结构化专属管线 (Phase 1-4)](#5-试卷结构化专属管线)
6. [集成点 — 三个 API 端点](#6-集成点--三个-api-端点)
7. [输出产物规范](#7-输出产物规范)
8. [配置项参考](#8-配置项参考)
9. [模块文件清单](#9-模块文件清单)

---

## 1. 架构概览

```
                         ┌──────────────────────────────┐
                         │     7 个文档入口              │
                         ├──────────────────────────────┤
                         │ Web KB 上传          │ POST /api/v1/knowledge/{kb}/upload
                         │ WeChat 文件          │ POST /api/process/file
                         │ MCP kb_upload_file   │ → POST /api/ingest/file
                         │ MCP process_file     │ → POST /api/process/file
                         │ MCP kb_upload_text   │ → POST /api/ingest/text
                         │ Web KB 同步          │ POST /api/kb/ingest-file
                         │ API 手动提取         │ POST /api/extract
                         └──────────┬───────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                  UnifiedDocumentPipeline.process(path)            │
│                                                                  │
│  ┌──────────┐    ┌──────────────┐    ┌─────────────────────┐    │
│  │ classify │ →  │   extract    │ →  │ structurize (可选)   │    │
│  │ 11 种类型 │    │ per-type     │    │ 仅 exam_pdf 触发     │    │
│  └──────────┘    └──────┬───────┘    └──────────┬──────────┘    │
│                         │                       │               │
│                         ▼                       ▼               │
│                    .txt sidecar           .exam.json sidecar     │
└──────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              Platform         DeepTutor         File
              ChromaDB         LlamaIndex        sidecars
```

**核心设计原则**：所有入口共享同一套分类→提取→结构化逻辑，通过 fire-and-forget 后台任务触发，不阻塞主请求。

---

## 2. 文档分类体系

`tutor_platform/rag/unified_pipeline.py` — `classify_file()` + `DocType` enum

### 分类规则

| DocType | 扩展名 | 内容嗅探规则 |
|---------|--------|------------|
| `text` | .txt, .md, .csv, .json, .yaml, .xml, .html, .py, .js, .ts, .css, .log | 按扩展名直接判定 |
| `image` | .jpg, .jpeg, .png, .gif, .webp, .bmp, .tiff, .heic | 按扩展名直接判定 |
| `text_pdf` | .pdf | fitz 提取文本 > 100 字符 |
| `scanned_pdf` | .pdf | fitz 提取文本 ≤ 100 字符 |
| `exam_pdf` | .pdf | 多页(>2) + 含图块，或单页有图 + 文本 > 200 字符 |
| `office_docx` | .docx | 按扩展名 |
| `office_xlsx` | .xlsx, .xls | 按扩展名 |
| `office_pptx` | .pptx, .pptm, .ppsx | 按扩展名 |
| `office_old` | .doc, .ppt, .pps | 按扩展名 |
| `office_other` | .odt, .rtf | 按扩展名 |
| `unknown` | 其他 | 兜底 |

---

## 3. 统一入口 — `UnifiedDocumentPipeline`

**文件**: `tutor_platform/rag/unified_pipeline.py`

```python
result = await UnifiedDocumentPipeline.process(
    file_path,
    llm_client=None,              # 可选，传入后启用 MiniCPM OCR
    enable_structured_exam=True,  # 考试 PDF 触发 Phase 1-4
    max_exam_pages=50,
)
# result.sidecar_paths  → [".txt", ".exam.json"]
# result.content_text  → 提取的纯文本
# result.doc_type      → DocType enum
```

**处理流程**:

1. `classify_file(path)` — 根据扩展名 + 内容嗅探返回 DocType
2. `_extract_*()` — 按类型调用对应提取器
3. `_write_sidecar(path, content, ".txt")` — 写出纯文本 sidecar
4. `_run_exam_pipeline()` — 仅当 `doc_type == exam_pdf` 且 `llm_client` 非空时触发 Phase 1-4

---

## 4. 各类型文档处理路径

### 4.1 纯文本文件 (TEXT)

```
.txt/.md/.py/...  →  多编码读取 (utf-8 → gbk → latin-1)  →  .txt
```

无 OCR，纯 I/O。

### 4.2 图片文件 (IMAGE)

```
.jpg/.png/...  →  base64 编码  →  MiniCPM-V OCR (Ollama)  →  .txt
```

需要 `llm_client`，prompt: "Transcribe all text from this image."

### 4.3 文字层 PDF (TEXT_PDF)

```
.pdf  →  fitz.open() → page.get_text()  →  拼接  →  .txt
```

纯 PyMuPDF，零 LLM 调用，<100ms/页。

### 4.4 扫描 PDF (SCANNED_PDF)

```
.pdf  →  fitz.open()  →  page.get_pixmap(dpi=200)  →  PNG
     →  base64  →  MiniCPM-V OCR (逐页)  →  拼接  →  .txt
```

逐页 OCR，需要 `llm_client`。有文字层的页直接走 TEXT_PDF 路径。

### 4.5 考试 PDF (EXAM_PDF)

```
.pdf  →  同 SCANNED_PDF 先提取纯文本
     →  然后触发 Phase 1-4 结构化管线 (见 §5)
     →  .txt + .exam.json
```

### 4.6 Office 文档 (OFFICE_*)

**新格式 (docx/xlsx/pptx)**:
```
.docx  →  python-docx 快速提取
.xlsx  →  openpyxl 快速提取
.pptx  →  python-pptx 快速提取
       →  失败则降级到 markitdown
       →  提取内嵌图片 (ZIP-based)
       →  .txt
```

**旧格式 (doc/ppt/xls) + 其他**:
```
.doc/.ppt/.xls/.odt/.rtf
       →  markitdown 提取 (优先)
       →  旧格式降级: antiword / catppt
       →  OLE 内嵌图片扫描
       →  .txt
```

**markitdown OCR layer** (>= 0.1.5):
```
markitdown.MarkItDown(llm_client=ollama_adapter)
    →  markitdown 自动识别并 OCR 文档内嵌图片
    →  当前版本: 0.1.6 (PyPI 最新)
```

**内嵌图片提取路径**:

| 格式 | 容器 | 提取方式 |
|------|------|---------|
| .docx/.pptx/.xlsx | ZIP | `_extract_zip_images_from_path()` 读取 `word/media/` `ppt/media/` `xl/media/` |
| .doc/.ppt/.xls | OLE | `_extract_ole_images_from_path()` 扫描流签名 (JPEG/PNG/GIF/BMP) |

---

## 5. 试卷结构化专属管线 (Phase 1-4)

**触发条件**: `DocType == exam_pdf` 且 `enable_structured_exam=True` 且 `llm_client` 非空

### 文件依赖

```
tutor_platform/rag/
├── layout_engine.py      ← Phase 1: 页→块
├── block_ocr.py          ← Phase 2: 块→OCR+图形描述
├── exam_structurer.py    ← Phase 3: 块→题
└── unified_pipeline.py   ← Phase 4: 串接+输出
```

### Phase 1: 布局引擎 (`layout_engine.py`)

**零 LLM 调用，纯 PyMuPDF，~100ms/页**

```
page.get_text("dict")       → 文本块 (type=0) + 图片块 (type=1), 含精确 bbox
page.get_drawings()         → 矢量图形分析:
                              线段多 → FigureHint.GEOMETRY
                              曲线多 → FigureHint.FUNCTION_GRAPH
                              矩形>4 → FigureHint.TABLE
                              其他   → FigureHint.ILLUSTRATION
page.get_image_info()       → 嵌入图片元数据 (xref, 尺寸, 色彩空间)
```

**输出**: `PageLayout[]` — 每页的 `LayoutBlock[]` 列表，含 `bbox`/`type`/`raw_text`/`figure_hint`/`needs_ocr`/`needs_description`

### Phase 2: 块级 OCR + 图形理解 (`block_ocr.py`)

**每个 block 单独裁剪为高 DPI 图片送 MiniCPM，而非全页一张图**

| Block 类型 | 处理 | Prompt |
|-----------|------|--------|
| text (needs_ocr) | `get_pixmap(clip=bbox, dpi=300)` → MiniCPM OCR | 精确转录 + LaTeX 公式 |
| image (needs_description) | `get_pixmap(clip=bbox, dpi=300)` + `figure_hint` → MiniCPM 描述 | 按 hint 分级 (geometry/function_graph/table/illustration) |

**并发策略**: 同页内 block 并发 (semaphore=3)，不同页顺序

**输出**: `BlockContent[]` — 每个 block 的 `text` 或 `description` (JSON)

### Phase 3: 语义结构化 (`exam_structurer.py`)

**纯规则，无 LLM**

```
BlockContent[] → 按 bbox.y 排序 → 题号正则分割 → 题型分类 → 配图关联
```

| 步骤 | 规则 |
|------|------|
| 题号检测 | `^\d{1,3}[．.、]` / `[(（]\d+[)）]` |
| 题型分类 | 选项 `A. B. C. D.` → choice; `___` → fill_blank; "解:" → solution |
| 配图关联 | `type=image` 的 block 紧邻的 `type=text` block → 配对该题 |
| 元数据提取 | 首页顶部 20% 区域 → 科目/年级/考试类型/年份/满分/时长 |

**输出**: `ExamPaper` — 含 `metadata` + `questions[]` (每题 content/type/options/figures/score)

### Phase 4: 输出

```
ExamPaper → JSON 序列化 → .exam.json sidecar
```

**.exam.json 结构**:

```json
{
  "paper_id": "uuid",
  "raw_file_hash": "sha256",
  "total_pages": 4,
  "metadata": {
    "subject": "math",
    "grade": "七年级",
    "exam_type": "midterm",
    "year": 2024,
    "total_score": 100,
    "duration_minutes": 90
  },
  "questions": [
    {
      "question_id": "uuid",
      "index": 1,
      "type": "choice",
      "content": "Markdown text with LaTeX formulas...",
      "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
      "answer": null,
      "score": 5.0,
      "page_num": 0,
      "figures": [
        {
          "figure_id": "uuid",
          "bbox": [100, 200, 300, 400],
          "description": { "figure_type": "triangle", "vertices": ["A","B","C"] }
        }
      ]
    }
  ]
}
```

---

## 6. 集成点 — 三个 API 端点

所有集成点在 `docker/platform/provider_api.py`，通过 `_spawn_unified_pipeline_bg()` 触发。

### 函数定义

```python
# provider_api.py:1078
def _spawn_unified_pipeline_bg(file_path: str, trace_id: str = "") -> None:
    """Submit file to unified pipeline as fire-and-forget background task."""

# provider_api.py:1100
async def _run_unified_pipeline_bg(file_path: str, trace_id: str) -> None:
    """Actual background task: import → classify → extract → structurize."""
```

### 调用点

| 端点 | 行号 | 调用时机 | 文件位置 | 触发场景 |
|------|------|---------|---------|---------|
| `POST /api/ingest/file` | 3700 | 文件写入 SOURCES_DIR 后 | `_spawn_unified_pipeline_bg(dest, trace_id)` | MCP 工具上传 |
| `POST /api/process/file` | 3584 | 文件写入 SOURCES_DIR 后 | `_spawn_unified_pipeline_bg(dest, trace_id)` | WeChat 文件上传 |
| `POST /api/kb/ingest-file` | 3208 | temp 文件准备好后 | `_spawn_unified_pipeline_bg(tmp_path, trace_id)` | Web UI KB 同步 |

### 设计要点

- **fire-and-forget**: `asyncio.create_task()` — 不阻塞主 HTTP 响应
- **容错**: 若文件已被删除（temp 文件清理），`_run_unified_pipeline_bg` 静默返回
- **平台容器零依赖**: `tutor_platform/rag/__init__.py` 使用 `__getattr__` 延迟加载，避免在 platform 容器中触发 deeptutor 导入

---

## 7. 输出产物规范

| 文件类型 | 产物 | 命名规范 | 内容 |
|---------|------|---------|------|
| 所有 | `.txt` | `{原文件名}.txt` | 提取的纯文本 (UTF-8) |
| exam_pdf | `.exam.json` | `{原文件名}.exam.json` | 结构化试卷 JSON |
| image blocks | PNG (future) | `{paper_id}/fig_{n}.png` | 裁剪的题目配图 |

**sidecar 写入策略**: 原子写入 (write → rename)，与原始文件在同一目录。

---

## 8. 配置项参考

### RAG Pipeline 配置 (`RAG_PIPELINE_*`)

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `RAG_PIPELINE_OCR_ENABLED` | `true` | 启用旧 OCR 阶段（逐页） |
| `RAG_PIPELINE_OCR_MAX_PAGES` | `50` | OCR 最大页数 |
| `RAG_PIPELINE_OCR_DPI` | `200` | 旧管线渲染 DPI |
| `RAG_PIPELINE_EXAM_STRUCTURING_ENABLED` | `true` | 启用结构化考试管线 |
| `RAG_PIPELINE_EXAM_OCR_DPI` | `300` | 块级 OCR 渲染 DPI |
| `RAG_PIPELINE_EXAM_MAX_CONCURRENT_BLOCKS` | `3` | 同页并发块数 |
| `RAG_PIPELINE_EXAM_SAVE_FIGURES` | `true` | 输出中保存图形 PNG |

### 模型配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `OLLAMA_URL` | `http://ollama:11434` | Ollama API 地址 |
| `OLLAMA_MODEL` | `minicpm-v` | OCR 模型 |

### markitdown OCR 配置

markitdown >= 0.1.5 内置 OCR layer (`MarkItDown(llm_client=...)`)，当前版本 **0.1.6 (PyPI 最新)**。`_get_markitdown_with_ocr()` 和 `_create_markitdown_llm_client()` 在 `provider_api.py` 中实现了一个轻量适配器，将 markitdown 的 LLM 协议映射到 Ollama `/api/chat` 端点。

---

## 9. 模块文件清单

### 新增文件 (本次迭代)

| 文件 | 行数 | 职责 |
|------|------|------|
| `tutor_platform/rag/unified_pipeline.py` | 575 | 统一入口：分类 → 提取 → 结构化 → sidecar |
| `tutor_platform/rag/layout_engine.py` | 270 | Phase 1：PyMuPDF 布局分析，零 LLM |
| `tutor_platform/rag/block_ocr.py` | 370 | Phase 2：块级 OCR + 图形描述，MiniCPM 分级 prompt |
| `tutor_platform/rag/exam_structurer.py` | 290 | Phase 3：块→题语义组装，纯规则 |
| `tutor_platform/rag/__init__.py` | 30 | 延迟加载，platform 容器零 deeptutor 依赖 |

### 修改文件 (本次迭代)

| 文件 | 改动 | 行数变化 |
|------|------|---------|
| `docker/platform/provider_api.py` | 添加 `_spawn_unified_pipeline_bg` + `_run_unified_pipeline_bg`；3 个 API 端点接入；markitdown OCR layer 适配器 | +150 |
| `tutor_platform/rag/pipeline.py` | 添加 `_stage_structured_exam` + `_structure_single_exam` + `_write_exam_sidecar` | +180 |
| `tutor_platform/rag/config.py` | 添加 4 个 `RAG_PIPELINE_EXAM_*` 配置项 | +5 |
| `docker-compose.dev.yml` | PYTHONPATH 修复 (platform 容器) | +1 |
| `tests/test_pipeline.py` | 更新测试预期适配 `.exam.json` sidecar | +2/-14 |

### 依赖关系

```
unified_pipeline.py
  ├── layout_engine.py       (Phase 1, 独立模块)
  ├── block_ocr.py           (Phase 2, 依赖 layout_engine 类型)
  ├── exam_structurer.py     (Phase 3, 依赖 block_ocr + layout_engine 类型)
  └── pipeline.py            (Phase 4 集成入口)

provider_api.py
  └── _spawn_unified_pipeline_bg()
      └── UnifiedDocumentPipeline.process()
          └── 以上全部
```

### 第三方依赖

| 库 | 版本 | 用途 |
|----|------|------|
| PyMuPDF (fitz) | >= 1.26.0 | PDF 文本提取、页渲染、布局分析、矢量分析 |
| markitdown | 0.1.6 | Office 文档提取 + 内嵌 OCR (>= 0.1.5) |
| python-docx | - | .docx 快速提取 |
| openpyxl | - | .xlsx 快速提取 |
| python-pptx | - | .pptx 快速提取 |
| olefile | - | .doc/.ppt/.xls OLE 图像扫描 |
| ollama (MiniCPM-V) | 4.6 | 块级 OCR + 图形描述 + 图表识别 |
