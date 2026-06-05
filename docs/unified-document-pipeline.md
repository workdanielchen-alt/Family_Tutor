# DeepTutor 统一文档处理架构

> 版本: 2.1 | 最后更新: 2026-06-05

## 目录

1. [架构概览](#1-架构概览)
2. [文档分类体系](#2-文档分类体系)
3. [统一提取层 — `extractors.py`](#3-统一提取层--extractorspy)
4. [统一入口 — UnifiedDocumentPipeline](#4-统一入口--unifieddocumentpipeline)
5. [各类型文档处理路径](#5-各类型文档处理路径)
6. [试卷结构化专属管线 (Phase 1-4)](#6-试卷结构化专属管线)
7. [集成点 — API 端点](#7-集成点--api-端点)
   - [7.1 KB 同步双写决策](#71-kb-同步双写决策)
   - [7.2 Sidecar 富化](#72-sidecar-富化)
8. [输出产物规范](#8-输出产物规范)
9. [并发安全与稳定性](#9-并发安全与稳定性)
10. [OpenCV 图像预处理管线](#10-opencv-图像预处理管线)
11. [语义分块策略](#11-语义分块策略)
12. [配置项参考](#12-配置项参考)
13. [模块文件清单](#13-模块文件清单)

---

## 1. 架构概览

### 入口矩阵 (6 条路径, 1 个统一提取层)

```
Web KB 上传  ─┐
WeChat 文件  ─┤
MCP 工具     ─┼─→ _handle_inbound_file()  ──→  extract_text() (extractors.py)
Web Proxy    ─┤       │                              │
DT 重建索引  ─┤    缓存 + vision           _EXTRACTOR_MAP dispatch
Extract API  ─┘     + sidecar 富化              │
                                          ┌───────┼───────┐
                                          ▼       ▼       ▼
                                        pdf    image   docx/xlsx/pptx
                                         │       │         │
                                    extract_pdf  OCR    python-docx
                                    _text()      │     /openpyxl
                                         │    OpenCV     /pptx
                                    ┌────┴────┐ 预处理       │
                                    │         │   │     markitdown
                               text_pdf   scanned   │     fallback
                               pymupdf4llm  pdf      │         │
                               (use_ocr    fitz render  ┌──────┴──────┐
                                =False)    + OpenCV     fast libs   markitdown
                                         + MiniCPM-V
                                         (5页/批并发,
                                          semaphore 1)
```

**核心设计原则**：6 条入口 → `_handle_inbound_file()` → `extractors.py` 的 `extract_text()`（唯一提取真相源）。所有文档类型的提取逻辑集中在 `tutor_platform/rag/extractors.py`，无重复实现。

### MiniCPM-V 手动 OCR 管线

扫描 PDF 不再需要 Tesseract。处理路径为：

```
_handle_pdf()
  ├─ extract_pdf_text(ocr_enabled=False)  ← 纯文字层提取, <1s
  │   └─ 剥除 "--- Page N ---" 分页标记后判断真实内容长度
  │        >50 chars → 文字层 PDF, 直接返回
  │
  └─ ≤50 chars → 扫描件
       └─ _pdf_manual_ocr_fallback()
            ├─ fitz 逐页渲染 (get_pixmap dpi=200)
            ├─ OpenCV 6步预处理 (降采样→灰度→降噪+CLAHE→deskew→二值化)
            ├─ 5页/批 asyncio.gather 并发
            ├─ _ocr_semaphore(1) 串行 MiniCPM-V OCR（CPU推理,并发2会过载超时）
            └─ 拼接 "--- Page N ---" 分页标记 + OCR 文本
```

> **为什么不直接用 pymupdf4llm 的 `ocr_function`？** pymupdf4llm v1.27+ 存在 OCR 合并 bug（结果被 silent-drop），直接逐页渲染 + MiniCPM-V 的手动路径更可靠且生产已验证。

### 扫描 PDF 入库完整链路

```
用户上传 scanned.pdf
  │
  ├─→ [Deeptutor] LlamaIndex 索引
  │      fitz.get_text() → 空 (无文本层) → 向量为 0
  │
  └─→ [Platform] POST /api/kb/ingest-file
         ├─ _handle_inbound_file()
         │   └─ _handle_pdf()
         │        ├─ extract_pdf_text(ocr_enabled=False) → 分页标记 2188 字
         │        ├─ 剥除标记 → 0 字真实内容 → 判定为扫描件
         │        └─ _pdf_manual_ocr_fallback()
         │             ├─ fitz.get_pixmap(dpi=200)
         │             ├─ preprocess_image_bytes (OpenCV 6步)
         │             └─ _ocr_semaphore(1) → ollama MiniCPM-V
         │             → 逐页 OCR 文本 (5页/批 asyncio.gather)
         │
         ├─ route == "document_extract" → **双写**
         │   └─ _ingest_to_kb(content, kb_name)
         │       ├─ ① ChromaDB: 语义分块 → embedding → /data/chromadb
         │       │    (ChromaDB 集合名经 _chromadb_kb_name() 自动映射)
         │       └─ ② DT LlamaIndex: .txt → POST /api/v1/knowledge/{kb}/upload
         │            (文件名追加 .txt 后缀, 不覆盖原始 PDF)
         │
         └─ _spawn_unified_pipeline_bg() → .txt / .exam.json sidecar
              └─ 后续 _enrich_with_sidecar_content() 消费更完整的 sidecar

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

## 3. 统一提取层 — `extractors.py`

**文件**: `tutor_platform/rag/extractors.py`

所有入口（`_handle_inbound_file` / `UnifiedDocumentPipeline` / `extract_text` API）最终都调用此模块的 `extract_text()` —— 它是文档提取的**唯一真相源**。

### `extract_text(file_path, *, trace_id="") → str`

按 `_EXTRACTOR_MAP` 根据扩展名自动分发到最优提取器：

```python
_EXTRACTOR_MAP = {
    ".pdf":  "pdf",       # → extract_pdf_text() (pymupdf4llm)
    ".docx": "docx",      # → extract_docx_text() → markitdown fallback
    ".xlsx": "xlsx",      # → extract_xlsx_text() → markitdown fallback
    ".pptx": "pptx",      # → extract_pptx_text() → markitdown fallback
    ".jpg":  "image",     # → extract_image_text() (OpenCV + MiniCPM OCR)
    ".png":  "image",     # → extract_image_text()
    ".webp": "image",
    ".heic": "image",
    ".doc":  "markitdown",
    ".ppt":  "markitdown",
    ".xls":  "markitdown",
    ".odt":  "markitdown",
    ".rtf":  "markitdown",
    ".epub": "markitdown",
    ".zip":  "markitdown",  # 递归遍历 ZIP 内容
    ".mp3":  "markitdown",  # 音频转录
    ".wav":  "markitdown",
    ".html": "html",        # 多编码读取 + XSS 消毒
}
```

### `extract_pdf_text(file_path, *, ocr_enabled=False, ocr_trace_id="") → str`

```python
# 文字层 PDF (默认): 结构化 Markdown, 无 OCR
text = extract_pdf_text("doc.pdf")

# 扫描 PDF: 启用 MiniCPM-V Hybrid OCR
text = extract_pdf_text("scanned.pdf", ocr_enabled=True, ocr_trace_id="task-1")
# ↓ 内部调用:
# pymupdf4llm.to_markdown(
#     path,
#     use_ocr=True,
#     ocr_function=get_minicpm_ocr_function(trace_id="task-1"),
# )
```

### `extract_image_text(file_path, *, trace_id="") → str`

```python
text = extract_image_text("photo.jpg", trace_id="task-1")
# ↓
# 1. 读取 raw bytes
# 2. OpenCV 6步预处理 (降采样→灰度→降噪+CLAHE→倾斜校正→二值化)
# 3. Ollama MiniCPM-V → rkllama NPU fallback OCR
# 4. 全图失败时自动水平缝隙分割 + 并行 OCR
```

### 其他提取器

| 函数 | 格式 | 策略 |
|------|------|------|
| `extract_docx_text` | .docx | python-docx → markitdown fallback |
| `extract_xlsx_text` | .xlsx | openpyxl (GFM 表格/Sheet) → markitdown fallback |
| `extract_pptx_text` | .pptx | python-pptx (Slide/Shape) → markitdown fallback |
| `extract_text_file` | .txt/.md/… | 多编码链: utf-8→gbk→gb2312→gb18030→latin-1→cp1252 |
| `extract_markitdown` | .epub/.doc/… | Microsoft markitdown 通用提取 |
| `extract_pdf_tables` | .pdf | PyMuPDF `page.find_tables()` → 结构化 `list[dict]` |
| `extract_pdf_tables_as_markdown` | .pdf | 同上，输出 GFM Markdown 表格 |
| `extract_pdf_embedded_images` | .pdf | `doc.get_page_images()` → 提取嵌入图片 bytes |
| `semantic_chunk` | 任意文本 | Markdown 标题感知分段 (§11) |

### HTML XSS 消毒

```python
_sanitize_html(html_text)  # 剥离 script/style/iframe/object/embed/on* handlers
```

### OCR 适配器 (`ocr_adapters.py`)

**文件**: `tutor_platform/rag/ocr_adapters.py`

```python
from tutor_platform.rag.ocr_adapters import MinicpmOCRFunc, get_minicpm_ocr_function

ocr_fn = MinicpmOCRFunc(trace_id="task-1")
# 签名: ocr_fn(fitz.Pixmap) → str
# 内部: pixmap → PNG bytes → OpenCV 预处理 → base64 → Ollama/rkllama OCR
```

适配器内部调用路径：
```
pymupdf4llm 检测到需 OCR 的区域
  → ocr_function(pixmap)
    → pixmap.tobytes("png")
    → preprocess_image_bytes() (OpenCV 6步)
    → OCR_PROVIDER=ollama → Ollama /api/chat (MiniCPM-V)
    → OCR_PROVIDER=rkllama → rkllama /v1/ocr (NPU)
    → garbled 检测 → 失败返回 ""
```

**关键：No Tesseract。** OCR 全程走现有 MiniCPM-V / rkllama 基建。

> **生产路径说明**: 当前生产代码中，扫描 PDF 的 OCR 不走 pymupdf4llm 的 `ocr_function` 回调（v1.27+ 存在合并 bug，结果 silent-drop），而是使用 `_handle_pdf()` 中的 `_pdf_manual_ocr_fallback()` — fitz 逐页渲染后 asyncio.gather 并发送 MiniCPM-V，见 §5.4。`MinicpmOCRFunc` 类保留以备 pymupdf4llm 修复后切换。

---

## 4. 统一入口 — `UnifiedDocumentPipeline`

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
# result.stats          → {file_type, extraction_chars, sidecars, ocr_called, ...}
```

**处理流程**:

1. `classify_file(path)` — 根据扩展名 + 内容嗅探返回 DocType
2. `_extract_*()` — 按类型调用对应提取器（图片/扫描 PDF 路径带 OpenCV 预处理）
3. `_write_sidecar(path, content, ".txt")` — 原子写出纯文本 sidecar
4. `_run_exam_pipeline()` — 仅当 `doc_type == exam_pdf` 且 `llm_client` 非空时触发 Phase 1-4

---

## 5. 各类型文档处理路径

所有路径以 `extractors.py` 的 `extract_text()` 为统一入口。`_handle_inbound_file()` 在调用 `extract_text()` 后追加 Vision description（图片）和 Office 内嵌图片 OCR。

### 5.1 纯文本文件 (TEXT)

```
.txt/.md/.py/...  →  extract_text_file() 多编码读取 (utf-8→gbk→gb2312→latin-1→cp1252)
                  →  run_in_executor 异步
```

html/.htm 额外经过 `_sanitize_html()` XSS 消毒。

### 5.2 图片文件 (IMAGE)

```
.jpg/.png/.heic/...
  →  extract_image_text()
       ├─ 1. 读取 raw bytes
       ├─ 2. OpenCV 6步预处理 (§10): 降采样(max 1800px)→灰度→降噪+CLAHE→倾斜校正→二值化
       ├─ 3. Ollama MiniCPM-V OCR (OCR_PROVIDER=ollama) / rkllama NPU (OCR_PROVIDER=rkllama)
       └─ 4. 全图失败 → 水平缝隙分割 → 并行 OCR
  →  _handle_inbound_file 追加: _describe_diagram() MiniCPM 图形描述
  →  短文本(<80 chars) 触发 tiered fallback 引导
```

### 5.3 文字层 PDF (TEXT_PDF)

```
.pdf → extract_pdf_text(path, ocr_enabled=False)
        → pymupdf4llm.to_markdown(use_ocr=False)
        → 结构化 Markdown (标题层级 + GFM 表格 + 阅读顺序 + 粗斜体)
        → pymupdf4llm 不可用 → raw pymupdf fallback
```

零 LLM 调用，~100ms/页。

### 5.4 扫描 PDF (SCANNED_PDF / EXAM_PDF)

```
.pdf → _handle_pdf()
        ├─ pymupdf4llm.to_markdown(use_ocr=False)
        │   → 仅 "--- Page N ---" 分页标记, 无文字
        ├─ 剥除分页标记 → _real_content ≤ 50 chars → 扫描件判定
        │
        └─ _pdf_manual_ocr_fallback()
             ├─ fitz.get_pixmap(dpi=200) → PNG bytes
             ├─ preprocess_image_bytes() (OpenCV 6步)
             ├─ 5页/批 asyncio.gather + _ocr_semaphore(1)
             │    → ollama /api/chat MiniCPM-V (CPU 推理, 并发 1)
             │    → OCR_PROVIDER=rkllama 时走 rkllama NPU
             └─ 拼接 "--- Page N ---\n{OCR 文本}" → 输出
```

**关键设计决策**：

| 维度 | 选择 | 原因 |
|------|------|------|
| OCR 引擎 | 手动 fitz 渲染 + MiniCPM-V | pymupdf4llm 的 `ocr_function` 有合并 bug（结果被 silent-drop） |
| 并发策略 | Semaphore(1) + 5页/批 gather | MiniCPM-V CPU 推理 ~350%/req，并发 2 导致超时/500 |
| 分页标记 | 保留 "--- Page N ---" | 下游分块和检索可用页码过滤 |
| 文字层判断 | `re.sub` 剥标记后 >50 chars | 121 页扫描件 = 2188 字分页标记 → 误判修复 |
| DT 写回 | 文件名追加 `.txt` | 不覆盖原始 PDF（下册曾被污染为纯文本） |

**性能**：

| 规模 | 耗时 | 说明 |
|------|------|------|
| 1 页 | ~9s | MiniCPM-V CPU 推理 |
| 121 页 (下册) | ~30-35min | Semaphore(1) 单请求, 零超时 |
| 5页/批 gather | ~45s/批 | 5 页并发送 MiniCPM, 内存 ~6MB |

### 5.5 Office 文档 (OFFICE_*)

**新格式 (docx/xlsx/pptx)**:
```
.docx → python-docx 快速提取 (run_in_executor 异步)
.xlsx → openpyxl 快速提取 (run_in_executor 异步)
.pptx → python-pptx 快速提取 (run_in_executor 异步)
      → 失败则降级到 markitdown
      → _ocr_office_images() 内嵌图片 OCR:
           ZIP 解包 (word/media/ ppt/media/ xl/media/) → OLE 扫描 (旧格式)
           → preprocess_image_bytes (OpenCV 6步) → _ocr_image_bytes (统一调度)
```

**旧格式 (doc/ppt/xls/odt/rtf) + EPUB**:
```
→ markitdown 提取 (run_in_executor 异步)
→ ZIP/OLE 内嵌图片扫描 (_extract_office_images)
```

### 5.6 EPUB / ZIP / 音频

```
.epub     → markitdown
.zip      → markitdown (递归遍历 ZIP 内容)
.mp3/.wav → markitdown (音频转录, 需 markitdown[all])
```

> **异步化**: Office 提取中的同步 I/O（`python-docx` / `openpyxl` / `markitdown`）全部通过 `loop.run_in_executor(None, ...)` 移至线程池执行，不阻塞事件循环。

**markitdown OCR layer** (>= 0.1.5): markitdown 部署为 `markitdown[all]` (含 audio-transcription / youtube-transcription extras)，版本 0.1.6。旧格式 `.doc` 由 markitdown 覆盖，**不依赖 antiword**。

**内嵌图片提取路径**:

| 格式 | 容器 | 提取方式 |
|------|------|---------|
| .docx/.pptx/.xlsx | ZIP | `_extract_zip_images_from_path()` 读取 `word/media/` `ppt/media/` `xl/media/` |
| .doc/.ppt/.xls | OLE | `_extract_ole_images_from_path()` 扫描流签名 (JPEG/PNG/GIF/BMP) |

---

## 6. 试卷结构化专属管线 (Phase 1-4)

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

## 7. 集成点 — API 端点

所有集成点在 `docker/platform/provider_api.py`。

### 调用点

| 端点 | 触发方式 | 触发函数 | 触发场景 |
|------|---------|---------|---------|
| `POST /api/process/file` | 同步调用 | `_handle_inbound_file()` | WeChat 文件 / MCP 工具上传 |
| `POST /api/kb/ingest-file` | 同步调用 | `_handle_inbound_file()` | Web UI KB 上传后同步 |
| `POST /api/ingest/file` | 同步调用 | `_handle_inbound_file()` | MCP 工具上传 (已废弃，统一用 process/file) |
| `POST /api/ingest/proxy/{kb}` | 同步调用 | `_handle_inbound_file()` | Web 代理上传 (DT 内部) |
| `POST /api/ingest/proxy` | 同步调用 | `_handle_inbound_file()` | Create KB + Ingest (新建 KB 同时上传) |
| `POST /api/kb/sync-from-dt` | 同步调用(批量) | `_handle_inbound_file()` per file | DT 重建索引后全量同步 |
| `POST /api/teach/start` | 同步调用 | `_ocr_file_base64()` → `_handle_inbound_file()` | Practice/WebUI 上传文件触发教学 |
| `POST /api/extract` | 同步调用 | `_handle_inbound_file()` | 轻量提取 (无入库) |
| `POST /api/ingest/text` | 直接入库 | `provider.ingest_text()` | MCP 文本入库 (不经文件提取) |
| `POST /api/ocr` | 同步调用 | `provider.ocr()` | 直接 OCR 调用 (无文件归档) |
| `POST /api/vision` | 同步调用 | `provider.vision()` | 图片描述/解题 (无文件归档) |

所有文件入口额外触发 `_spawn_unified_pipeline_bg()` — fire-and-forget 后台任务，产生 `.md` / `.exam.json` sidecar。`/api/ingest/proxy/{kb}` 也已补全此调用。

### 7.1 KB 同步双写决策

`POST /api/kb/ingest-file` 是 KB 扫描 PDF 入库的关键路径。它根据文件 OCR 路由决定写策略：

```
Web UI KB 上传 scanned.pdf
  └─→ Deeptutor 侧 (LlamaIndex): fitz 提取文字 → 空 (扫描版无文本层)
       → LlamaIndex 索引的是空向量 🔴

前端 fire-and-forget ──→ POST /api/kb/ingest-file
  └─→ _handle_inbound_file() → OCR 出正文
       │
       ├─ route == "ocr" / "document_extract"
       │    → _ingest_to_kb() 双写:
       │       ① ChromaDB (平台向量库)
       │       ② DT LlamaIndex (创建 .txt → upload API 回写)
       │
       └─ route == "text_extract" (文字层 PDF, DT 已有完整文本)
            → 仅写 ChromaDB (不重复写 DT)
```

| 路由 | 文件类型 | ChromaDB | DT LlamaIndex | 说明 |
|------|---------|----------|--------------|------|
| `ocr` | 图片文件 | ✅ | ✅ 双写 | OCR 出正文，DT 没有 |
| `document_extract` | 扫描 PDF / Office | ✅ | ✅ 双写 | OCR/markitdown 出正文，DT 没有 |
| `text_extract` | 文字层 PDF / 纯文本 | ✅ | ❌ 不写 | DT 已有完整文本层索引 |
| `ocr_fallback` | OCR 部分失败 | ❌ | ❌ | 质量不足不入库 |

**`_ingest_to_kb()` 双写流程**（`provider_api.py:2039`）:
1. 生成教学摘要（v3, best-effort）
2. 语义分块后写入平台 ChromaDB（`provider.add_documents()`，使用 `semantic_chunk()`）
3. 创建临时 `.txt` → 通过 `POST /api/v1/knowledge/{kb}/upload` 回写 DT LlamaIndex

### 7.2 Sidecar 富化

`_enrich_with_sidecar_content()` 在 `_handle_inbound_file()` 中消费 `UnifiedDocumentPipeline` 的 `.md` sidecar：

```python
content = _enrich_with_sidecar_content(content, file_path)
# → 若 {原文件名}.md sidecar 存在且长度 > 内联提取 × 1.2 → 使用 sidecar
```

`_inject_doc_type_meta()` 将 `DocType` 分类结果注入 metadata 供 RAG 检索过滤：

```python
{"doc_subtype": "text_pdf"}  # 来自 classify_file() → DocType
```

> **关联文档**: `docs/ingestion-index-architecture.md` — 归一化入库索引方案：完整入口矩阵、格式→提取器→路由→双写决策表、ChromaDB 存储规范、Metadata Schema — 与本文档互补阅读。

---

## 8. 输出产物规范

| 文件类型 | 产物 | 命名规范 | 内容 |
|---------|------|---------|------|
| 所有 | `.txt` | `{原文件名}.txt` | 提取的纯文本 (UTF-8) |
| exam_pdf | `.exam.json` | `{原文件名}.exam.json` | 结构化试卷 JSON |
| image blocks | PNG (future) | `{paper_id}/fig_{n}.png` | 裁剪的题目配图 |

**sidecar 写入策略**: 原子写入 (write → rename)，与原始文件在同一目录。

---

## 9. 并发安全与稳定性

### 8.1 全局并发控制

```
                         _UNIFIED_PIPELINE_SEMAPHORE (max=2)

  请求A ──→ spawn() ──→ 获取 Semaphore ✓ ──→ 运行 pipeline ──→ 释放
  请求B ──→ spawn() ──→ 获取 Semaphore ✓ ──→ 运行 pipeline ──→ 释放
  请求C ──→ spawn() ──→ 等待 Semaphore... ──→ (请求B完成)→ ✓ ──→ 运行
```

**机制**: `asyncio.Semaphore(RAG_PIPELINE_MAX_CONCURRENT_TASKS)` 全局限制同时运行的后台任务数。

**为什么需要**：`fire-and-forget` 不等于 `fire-unlimited`。N 个并发文件上传各 spawn 一个后台任务，每个任务内部又扇出 M 个 MiniCPM 调用——不做限制会导致后端过载（Ollama OOM / 超时雪崩）。

### 8.2 任务超时保护

| 层级 | 超时 | 说明 |
|------|------|------|
| 后台任务整体 | 600s (`RAG_PIPELINE_TASK_TIMEOUT_S`) | 超时后 `asyncio.wait_for` 取消任务，释放 Semaphore |
| 单次 LLM 调用 | 120s | 每个 `llm_client.complete()` 包裹 `asyncio.wait_for(..., timeout=120)` |
| 块级 OCR | 120s/block | BlockOCREngine 继承统一管线的 120s 限制 |

**为什么需要**: 卡住的 Ollama 调用会永久占用 Semaphore 槽位，导致所有后续请求排队直到 OOM。

### 9.3 OCR 并发策略 — `_ocr_semaphore(1)`

```
for batch_start in range(0, 121, BATCH=5):
    tasks = [_ocr_one_page(i) for i in batch_start:batch_start+5]
    results = await asyncio.gather(*tasks)
    # task 内部: _ocr_semaphore(1) → 一次只有一个 MiniCPM-V 请求
```

**为什么 Semaphore(1) 而不是 2？**

| Semaphore 值 | 效果 |
|:-----------:|------|
| 2 | 两个并发 Ollama 请求争抢 MiniCPM-V，CPU 726% 过载 → 间歇性超时/500 |
| 1 | 单请求稳定执行，~9s/页，零超时 |

**为什么 gather 批量为 5？**

| 批量 | Peak 内存 | CPU 尖峰 | 安全性 |
|:---:|--------|:------:|:---:|
| 121 (全量) | ~140MB | 18s 连续 | ❌ 可能 OOM |
| 5 | ~6MB | 0.75s | ✅ 稳定 |
| 1 | ~1.2MB | 随时 | ✅ 最安全但太慢 |

### 9.4 Office 提取异步化

所有同步 I/O 调用移至线程池：

```python
# 旧: 同步阻塞事件循环
text = _extract_docx_fast(path)

# 新: 线程池执行
loop = asyncio.get_running_loop()
text = await loop.run_in_executor(None, _extract_docx_fast, path)
```

适用: `python-docx`, `openpyxl`, `python-pptx`, `markitdown`, 文本文件解码。

### 9.5 任务去重

```
_spawn_unified_pipeline_bg()
  └─ SHA-256(file) → _UNIFIED_PIPELINE_STATUS
     ├─ 已存在且 status=="running" → skip (去重)
     └─ 不存在 → create_task() + 记录 "queued"
```

### 9.6 结果追踪 API

```
GET /api/pipeline/status?file_hash=<sha256>

→ {"ok": true, "found": true, "status": "done", "doc_type": "text_pdf",
     "sidecars": [...], "elapsed_s": 2.3}

GET /api/pipeline/status

→ {"ok": true, "total_tracked": 3,
     "by_status": {"queued": 0, "running": 1, "done": 2, "failed": 0},
     "pipeline_semaphore": {"max": 2, "locked": true}}
```

---

## 10. OpenCV 图像预处理管线

所有图片 OCR 路径（§5.2 图片文件 + §5.5 Office 内嵌图片 + §3 `extract_image_text` + `ocr_adapters.py` MiniCPM 适配器 + §5.4 扫描 PDF）统一经过 6 步预处理：

```
原始图片 bytes
  │
  ├─ 1. 降采样 (max 1800px)
  │      MiniCPM-V 最佳输入 1.8M 像素，超限等比缩放
  │      cv2.resize(..., INTER_AREA)
  │
  ├─ 2. 灰度化
  │      cv2.COLOR_BGR2GRAY
  │      去除颜色通道噪声
  │
  ├─ 3. 降噪 + CLAHE
  │      高对比度图片 (std > 40, 如手机截图) → 跳过，节省 40-60% CPU
  │      低对比度 → cv2.fastNlMeansDenoising + CLAHE(clipLimit=2.0, 8×8)
  │
  ├─ 4. 倾斜校正 (deskew)
  │      cv2.minAreaRect 检测文字方向角
  │      倾斜 > 0.3° → cv2.warpAffine 旋转校正
  │
  ├─ 5. 自适应二值化
  │      cv2.adaptiveThreshold(ADAPTIVE_THRESH_GAUSSIAN_C, 11, 2)
  │      黑白二值 → OCR 引擎最优输入
  │
  └─ 6. JPEG 编码输出
         quality=95, 返回 bytes
```

**实现位置**: `tutor_platform/tools/preprocess.py::preprocess_image_bytes()`

**应用路径**:
- `extract_image_text()` — extractors.py 图片 OCR
- `_pdf_manual_ocr_fallback()` — provider_api.py 扫描 PDF OCR (5页/批 gather)
- `_ocr_office_images()` — provider_api.py Office 内嵌图片 OCR
- `MinicpmOCRFunc.__call__()` — ocr_adapters.py pymupdf4llm 适配器

**降级策略**: OpenCV 不可用时直接返回原始字节，MiniCPM 仍可处理原始图片。

---

## 11. 语义分块策略

**实现**: `tutor_platform/rag/extractors.py::semantic_chunk()`

替换旧的 `_split_content_for_ingest()` (500 字符段落截断) 为语义感知分块。

### 策略

```python
chunks = semantic_chunk(
    text,
    chunk_size=800,       # 默认值, 可通过 RAG_CHUNK_SIZE 环境变量配置
    chunk_overlap=100,    # 前一 chunk 末尾拼接到后一 chunk 开头
    doc_type="text_pdf",  # metadata 透传
    filename="doc.pdf",
)
```

**分块优先级**:
1. **按 Markdown 标题切割** (## / ### / ####) — 保持知识点完整性
2. **段落边界** (\n\n) — 标题内段落过长时 fallback
3. **硬截断** — 最后一着

### Chunk Metadata

每个 chunk dict 包含：
```python
{
    "text": "chunk 内容 (含 overlap 前缀)",
    "heading_path": "第3章 > 勾股定理",  # Markdown 标题面包屑
    "chunk_index": 0,
    "char_count": 780,                   # 本 chunk 自身长度 (不含 overlap)
    "doc_type": "text_pdf",
    "filename": "math_textbook.pdf",
}
```

### Overlap 机制

```
Chunk 1: [.....................]  ← char_count=750
                                    overlap = 末尾100字符
Chunk 2: [overlap前缀\n\n正文......]  ← 开头含上一 chunk 的末尾
```

确保跨段落边界的检索不丢失上下文。

### 配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `RAG_CHUNK_SIZE` | `800` | 目标 chunk 大小 (字符数) |

---

### 中文 KB 名 ChromaDB 映射 — `_chromadb_kb_name()`

ChromaDB 要求 collection 名为 `[a-zA-Z0-9._-]`（64 字符内）。`_chromadb_kb_name()` 在 `provider_api.py:802` 自动映射：

```python
_chromadb_kb_name("tutoring")    → "tutoring"        # ASCII 直通
_chromadb_kb_name("初中教材")    → "kb_Zu4F3wD-a-s"   # SHA256→base64url
_chromadb_kb_name("数学练习")    → "kb_4fIj150sJUQ"
```

**所有代码路径使用同一函数**：`_ingest_to_kb()`、`api_kb_ingest_file()`、`api_kb_sync_from_dt()`、`api_kb_search()`。

DT API 调用侧的 KB 名始终使用**原始中文名**（如 `初中教材`），仅 ChromaDB collection 名做映射。

**`api_kb_sync_from_dt` URL 编码修复**：
- KB 名用 `urllib.parse.quote()` 编码后才拼入 DT API URL
- DT `/api/v1/knowledge/{kb}/files` 返回 `{"files": [...]}` dict 而非直接列表 — 已适配
- 下载 URL 同理使用编码后的 `_safe_kb` + `_safe_name`



---

## 12. 配置项参考

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
| **`RAG_PIPELINE_MAX_CONCURRENT_TASKS`** | **`2`** | **全局并发后台任务数 (§8.1)** |
| **`RAG_PIPELINE_TASK_TIMEOUT_S`** | **`600`** | **单任务超时秒数 (§8.2)** |

### 模型配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `OLLAMA_URL` | `http://ollama:11434` | Ollama API 地址 |
| `OLLAMA_OCR_MODEL` | `openbmb/minicpm-v4.6:q4_K_M` | OCR 模型 (1.5GB CPU 推理) |
| `RKLLAMA_URL` | `http://rkllama:8080` | rkllama NPU API 地址 |
| `OCR_PROVIDER` | `ollama` | OCR 后端选择: `ollama` (MiniCPM-V) 或 `rkllama` (NPU) |
| `RAG_CHUNK_SIZE` | `800` | semantic_chunk() 目标 chunk 大小 (字符数) |
| `OLLAMA_KEEP_ALIVE` | `15m` | Ollama 模型常驻时间 |

### 乱码检测

`_ocr_output_is_garbled()` 仅检测两种确定性失败：
- **U+FFFD 替换字符过多** (>5%): 编码损坏
- **STUB 模式输出**: `[STUB:DeepSeekOCR-3B]` — rkllama 未真实运行

> 已移除基于 `chinese_ratio < 0.2` 的启发式规则 — 该规则曾误杀 MiniCPM-V 对化学教材扫描件的合法中文输出。

### markitdown OCR 配置

markitdown >= 0.1.5 内置 OCR layer (`MarkItDown(llm_client=...)`)，部署为 `markitdown[all]` 版本 0.1.6。`_get_markitdown_with_ocr()` 和 `_create_markitdown_llm_client()` 在 `provider_api.py` 中实现了一个轻量适配器，将 markitdown 的 LLM 协议映射到 Ollama `/api/chat` 端点。

---

## 13. 模块文件清单

### 新增文件

| 文件 | 行数 | 职责 |
|------|------|------|
| `tutor_platform/rag/extractors.py` | ~800 | **统一提取层**：`extract_text()` 单一真相源，11 种格式分发，image/HTML/pdf/docx/xlsx/pptx 提取器，语义分块 `semantic_chunk()` |
| `tutor_platform/rag/ocr_adapters.py` | ~220 | **MiniCPM OCR 适配器**：`MinicpmOCRFunc` 实现 pymupdf4llm `ocr_function` 协议，Ollama/rkllama OCR dispatch |
| `tutor_platform/rag/unified_pipeline.py` | ~500 | 统一入口：分类 → 提取 → 结构化 → sidecar |
| `tutor_platform/rag/layout_engine.py` | 270 | Phase 1：PyMuPDF 布局分析，零 LLM |
| `tutor_platform/rag/block_ocr.py` | 370 | Phase 2：块级 OCR + 图形描述，MiniCPM 分级 prompt |
| `tutor_platform/rag/exam_structurer.py` | 290 | Phase 3：块→题语义组装，纯规则 |
| `tutor_platform/rag/__init__.py` | 30 | 延迟加载，platform 容器零 deeptutor 依赖 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `docker/platform/provider_api.py` | `_handle_pdf`: 文字层快读 → 分页标记剥离 → 扫描件 `_pdf_manual_ocr_fallback` (5页/批 gather + Semaphore(1) MiniCPM-V)；`_handle_inbound_file` 委托给 `extract_text()`；新增 `_chromadb_kb_name()` 中文KB名映射；新增 `_enrich_with_sidecar_content` / `_inject_doc_type_meta`；`_ocr_office_images` 统一走 `preprocess_image_bytes` + `_ocr_image_bytes`；`_ocr_output_is_garbled` 简化为仅检测 STUB/U+FFFD；`_ocr_semaphore(1)` (CPU 推理避免并发超时)；`_ingest_to_kb` DT 写回追加 `.txt` 后缀避免覆盖原始 PDF；`api_kb_sync_from_dt` 用 `Form()` + URL 编码 + DT 响应格式适配 |
| `tutor_platform/rag/pipeline.py` | `_stage_structured_exam` + `_structure_single_exam` + `_write_exam_sidecar` |
| `tutor_platform/rag/config.py` | 添加 `RAG_PIPELINE_EXAM_*` + `RAG_PIPELINE_MAX_CONCURRENT_*` 配置项 |
| `docker/platform/Dockerfile` | `markitdown[all]` + `pymupdf4llm` + 阿里云镜像；移除 `antiword` |
| `docker-compose.yml` | `OCR_PROVIDER=ollama` |
| `tests/test_deployment_e2e.py` | 24 个 E2E 测试 (6入口 × 5文档类型 + 检索 + 双写 + 回归) |
| `tests/test_ingestion_consistency.py` | 20 个单元测试 (提取一致性 / OCR / 表格 / 语义分块 / 分类 / sidecar 富化) |

### 依赖关系

```
extractors.py  ← 统一提取层 (所有入口的单一真相源)
  ├── ocr_adapters.py            (MiniCPM OCR 适配器, pymupdf4llm 集成)
  ├── tools/preprocess.py        (OpenCV 6步预处理)
  ├── markitdown                 (通用文档转换)
  ├── python-docx / openpyxl / python-pptx  (Office 快速提取)
  └── _sanitize_html()           (HTML XSS 消毒, 内置)

unified_pipeline.py
  ├── extractors.py              (文本提取)
  ├── layout_engine.py            (Phase 1, 独立模块)
  ├── block_ocr.py                (Phase 2, 依赖 layout_engine 类型)
  ├── exam_structurer.py          (Phase 3, 依赖 block_ocr + layout_engine 类型)
  └── pipeline.py                 (Phase 4 集成入口)

provider_api.py
  ├── extractors.py              (_handle_inbound_file 委托提取)
  ├── ocr_adapters.py            (间接通过 extract_pdf_text)
  └── _spawn_unified_pipeline_bg()
      ├── SHA-256 去重
      ├── _ocr_semaphore(1) (OCR 并发控制, MiniCPM-V 单请求)
      └── _run_unified_pipeline_bg()
          ├── asyncio.wait_for(600s)
          └── UnifiedDocumentPipeline.process()
              └── 以上全部
```

### 第三方依赖

| 库 | 版本 | 用途 |
|----|------|------|
| PyMuPDF (fitz) | >= 1.26.0 | PDF 文本提取、页渲染、布局分析、表格检测、矢量分析 |
| pymupdf4llm | >= 1.27.0 | 文字层 PDF 结构化 Markdown 提取 (use_ocr=False)；OCR 走 _pdf_manual_ocr_fallback |
| OpenCV (cv2) | - | 图片降采样、灰度化、降噪、CLAHE、倾斜校正、二值化 |
| markitdown[all] | 0.1.6 | Office/EPUB/ZIP/音频 文档提取 + 内嵌 OCR |
| python-docx | - | .docx 快速提取 (run_in_executor 异步) |
| openpyxl | - | .xlsx 快速提取 (run_in_executor 异步) |
| python-pptx | - | .pptx 快速提取 (run_in_executor 异步) |
| olefile | - | .doc/.ppt/.xls OLE 图像扫描 |
| MiniCPM-V (via Ollama) | 4.6 | 图片 OCR + Office 内嵌 OCR + PDF 扫描页 OCR (3 条路径统一 `_ocr_image_bytes`) |
| rkllama (NPU) | - | 替代 OCR 后端 (OCR_PROVIDER=rkllama) |
