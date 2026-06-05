# DeepTutor 文档入库归一化索引方案

> 版本: 1.0 | 区域: `/docs/` | 最后更新: 2026-06-05

## 目录

1. [方案总览](#1-方案总览)
2. [入口归一化矩阵](#2-入口归一化矩阵)
3. [格式→提取器→路由→索引决策表](#3-格式提取器路由索引决策表)
4. [ChromaDB 存储层](#4-chromadb-存储层)
5. [DT LlamaIndex 同步策略](#5-dt-llamaindex-同步策略)
6. [Sidecar 富化时序](#6-sidecar-富化时序)
7. [Metadata Schema](#7-metadata-schema)
8. [并发安全与并发控制](#8-并发安全与并发控制)
9. [补充资料：现有文档](#9-补充资料现有文档)

---

## 1. 方案总览

### 归一化原则

```
所有入口 (8 条)       统一提取层              双存储层              Sidecar
──────────────      ────────────           ──────────           ────────
WeChat 文件 ─┐
Web UI KB   ─┤
MCP 工具    ─┤
Web Proxy   ─┼──→ _handle_inbound_file() ──→ ChromaDB ──→  .txt
Create KB   ─┤          │                    (语义分块)   .exam.json
DT 重建索引 ─┤    extract_text()               +            .figures/
Practice    ─┤    (唯一提取真相源)         DT LlamaIndex
Text API    ─┤                           (条件双写)
Extract API ─┘
```

**核心约束**：

| 约束 | 说明 |
|------|------|
| **唯一提取真相源** | `tutor_platform/rag/extractors.py` 的 `extract_text()` — 所有路径最终都收敛于此 |
| **KB 必须先存在** | 任何入库操作前都会 `_check_kb_exists_on_dt()` — 绝不自动创建 KB |
| **确定性 ID** | ChromaDB 文档 ID = `sha256(content)[:16]_chunk_index` — 同内容自动覆盖不重复 |
| **内容 hash 去重** | `_FILE_PROCESS_CACHE` (30min TTL, SHA256) — 短时间重复发图跳过处理 |

### 架构图

```mermaid
flowchart TD
    subgraph Entry[入口层]
        WX["WeChat 文件<br/>_route_child_message()"]
        WEB["Web UI KB<br/>knowledge-api.ts"]
        MCP["MCP 工具<br/>rag/read_file 等"]
        PROXY["Web Proxy<br/>/api/ingest/proxy"]
        CREATE["Create KB<br/>/api/ingest/proxy"]
        SYNC["DT 重建索引<br/>/api/kb/sync-from-dt"]
        TEACH["Practice<br/>/api/teach/start"]
        TEXT["Text API<br/>/api/ingest/text"]
    end

    subgraph Extract[统一提取层]
        HANDLER["_handle_inbound_file()<br/>provider_api.py:1213"]
        EXTRACT["extract_text()<br/>extractors.py:625"]
        CLASSIFY["classify_file()<br/>unified_pipeline.py:78"]
    end

    subgraph Routes[路由标记]
        OCR["route=ocr<br/>图片/扫描PDF"]
        DOC["route=document_extract<br/>处理后的PDF"]
        TEXT_PDF["route=text_extract<br/>文字层PDF/Office"]
        PASS["route=passthrough<br/>无有效内容"]
    end

    subgraph Storage[双存储层]
        CHROMA["ChromaDB<br/>+ 教学摘要(LLM)<br/>collection: kb_xxx_a-z"]
        DTIDX["DT LlamaIndex<br/>+ .txt file upload<br/>条件: ocr/document_extract"]
    end

    subgraph Sidecar[Sidecar 富化]
        TXT[".txt sidecar"]
        EXAM[".exam.json"]
        FIGS[".figures/"]
    end

    WX --> HANDLER
    WEB --> HANDLER
    MCP --> HANDLER
    PROXY --> HANDLER
    CREATE --> HANDLER
    SYNC --> HANDLER
    TEACH --> HANDLER
    TEXT -.-> CHROMA

    HANDLER --> EXTRACT
    EXTRACT --> CLASSIFY
    CLASSIFY --> OCR
    CLASSIFY --> DOC
    CLASSIFY --> TEXT_PDF
    CLASSIFY --> PASS

    OCR --> CHROMA
    OCR --> DTIDX
    DOC --> CHROMA
    DOC --> DTIDX
    TEXT_PDF --> CHROMA
    PASS -.-> |跳过| CHROMA

    HANDLER -.-> |_spawn_unified_pipeline_bg()| TXT
    HANDLER -.-> |_spawn_unified_pipeline_bg()| EXAM
    HANDLER -.-> |_spawn_unified_pipeline_bg()| FIGS
```

---

## 2. 入口归一化矩阵

### 全量入口

| # | 入口端 | 触发条件 | API 端点 | 处理函数 | source 标记 |
|---|--------|---------|----------|---------|-----------|
| 1 | **WeChat 家长发图** | 微信文件消息 | `POST /api/process/file` | `api_process_file()` → `_handle_inbound_file()` | `"mcp"` |
| 2 | **Web UI KB 上传** | DT 知识库页面上传 | `POST /api/kb/ingest-file` | `api_kb_ingest_file()` → `_handle_inbound_file()` | `"web_ui"` |
| 3 | **MCP 工具 (rag/read_file)** | Agent 调用 | `POST /api/process/file` | `api_process_file()` → `_handle_inbound_file()` | `"mcp"` |
| 4 | **Web Proxy (DT 内部)** | Agent tool `kb_lookup_concept` 等 | `POST /api/ingest/proxy/{kb_name}` | `api_ingest_proxy()` → `_handle_inbound_file()` | `"web"` |
| 5 | **Create KB + Ingest** | Web UI 新建 KB 同时上传 | `POST /api/ingest/proxy` | `api_create_kb_and_ingest()` → `_handle_inbound_file()` | `"web"` |
| 6 | **DT 重建索引同步** | Web UI 点"重建索引"后 | `POST /api/kb/sync-from-dt` | `api_kb_sync_from_dt()` → 从 DT 下载 → `_handle_inbound_file()` | `"web_ui_reindex"` |
| 7 | **Practice 教学习题** | Web App `/practice` 上传文件 | `POST /api/teach/start` | `api_teach_start()` → `_ocr_file_base64()` → `_handle_inbound_file()` | `"webui"` |
| 8 | **Text API** | 直接文本入库（无文件） | `POST /api/ingest/text` | `api_ingest_text()` → 跳过 `_handle_inbound_file()` | `"api"` |

### 路径收敛示意

```
入口 1-7 ──→ _handle_inbound_file()
               ├─ SHA256 去重 (30min TTL, per-learner)
               ├─ OCR warm-check (持久化标记)
               ├─ extract_text()  ← 唯一提取真相源
               ├─ Vision description (图片文件)
               ├─ Educational intent 检测
               ├─ 路由标记: ocr / document_extract / text_extract / passthrough
               └─ _maybe_ingest_result()  ← 双写决策
                    ├─ route in ("ocr", "document_extract")
                    │   └─ _ingest_to_kb()  → ChromaDB + DT LlamaIndex
                    └─ 其他
                        └─ 仅 ChromaDB (DT 已有文本)

入口 8   ──→ provider.ingest_text()  → 仅 ChromaDB
```

### 各入口差异

| 维度 | WeChat | Web UI KB | MCP | Proxy | Create | Sync | Practice |
|------|--------|----------|-----|-------|--------|------|----------|
| kb_name | 可选 | 必传 | 可选 | 路径参数 | 必传 | 必传 | 无 |
| learner_id | WeChat ID | "web" | "default" | "default" | "default" | 无 | "default" |
| 文件归档 | SOURCES_DIR | SOURCES_DIR | SOURCES_DIR | SOURCES_DIR | SOURCES_DIR | tmp 临时 | tmp 临时 |
| Sidecar 触发 | ✅ 后台 | ✅ 后台 | ✅ 后台 | ✅ 后台 | ✅ 后台 | ❌ | ❌ |
| Teaching 启动 | ✅ 异步 | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 同步 |
| 通知 HA | ✅ OCR失败 | ✅ 完成/失败| ❌ | ❌ | ❌ | ❌ | ❌ |

---

## 3. 格式→提取器→路由→索引决策表

### 完整决策矩阵

| 文件扩展名 | 提取器函数 | 提取方式 | route 标记 | ChromaDB | DT LlamaIndex | 说明 |
|-----------|-----------|---------|-----------|----------|--------------|------|
| `.pdf` (文字层) | `extract_pdf_text()` | pymupdf4llm → 结构化 Markdown | `text_extract` | ✅ 仅 ChromaDB | ❌ DT 已有原文 | DT 已索引原始 PDF |
| `.pdf` (扫描件) | `extract_pdf_text()` → `_pdf_manual_ocr_fallback()` | fitz 渲染 + MiniCPM-V OCR | `document_extract` | ✅ 双写 | ✅ 写回 .txt | DT 无文本层须回写 |
| `.pdf` (考试) | `extract_pdf_text()` → `_pdf_manual_ocr_fallback()` + Phase 1-4 | OCR + 布局+结构化 | `document_extract` | ✅ 双写 | ✅ 写回 .txt + .exam.json | 额外产出结构化 sidecar |
| `.jpg`, `.jpeg`, `.png` | `extract_image_text()` | OpenCV + MiniCPM/rkllama OCR | `ocr` | ✅ 双写 | ✅ 教学摘要后写回 | 短文本触发 tiered fallback |
| `.gif`, `.webp`, `.bmp`, `.tiff`, `.tif`, `.heic` | `extract_image_text()` | OpenCV + MiniCPM/rkllama OCR | `ocr` | ✅ 双写 | ✅ 教学摘要后写回 | 同上 |
| `.docx` | `extract_docx_text()` | python-docx → markitdown fallback | `document_extract` | ✅ 双写 | ✅ 写回 | Office 新格式 |
| `.xlsx` | `extract_xlsx_text()` | openpyxl → markitdown fallback | `document_extract` | ✅ 双写 | ✅ 写回 | 含 GFM 表格 |
| `.pptx`, `.pptm`, `.ppsx` | `extract_pptx_text()` | python-pptx → markitdown fallback | `document_extract` | ✅ 双写 | ✅ 写回 | 含嵌入式图片 OCR |
| `.doc`, `.ppt`, `.pps`, `.xls` | `extract_markitdown()` | markitdown | `document_extract` | ✅ 双写 | ✅ 写回 | 旧 Office 格式 |
| `.odt`, `.rtf` | `extract_markitdown()` | markitdown | `document_extract` | ✅ 双写 | ✅ 写回 | |
| `.epub` | `extract_markitdown()` | markitdown | `document_extract` | ✅ 双写 | ✅ 写回 | |
| `.zip` | `extract_markitdown()` | markitdown 递归遍历 | `document_extract` | ✅ 双写 | ✅ 写回 | |
| `.mp3`, `.wav`, `.ogg` | `extract_markitdown()` | markitdown 音频转录 | `document_extract` | ✅ 双写 | ✅ 写回 | 需 markitdown[all] |
| `.html`, `.htm` | `extract_text_file()` + `_sanitize_html()` | 多编码读取 + XSS 消毒 | `text_extract` | ✅ 仅 ChromaDB | ❌ | |
| `.txt`, `.md`, `.csv`, `.json`, `.yaml`, `.xml` | `extract_text_file()` | 多编码 fallback 链 | `text_extract` | ✅ 仅 ChromaDB | ❌ | |
| 源代码 (`.py`, `.js`, `.ts`, `.c`, `.go`, …) | `extract_text_file()` | 多编码 fallback 链 | `text_extract` | ✅ 仅 ChromaDB | ❌ | |
| 其他 (`.tex`, `.bib`, `.sgf`, …) | `extract_text_file()` → `extract_markitdown()` fallback | 尽力 | `text_extract` 或 `passthrough` | ✅ 尽力 | ❌ | |

### 路由标记 → 双写决策

```
route ∈ {"ocr", "document_extract"}  ──→ 双写 (ChromaDB + DT LlamaIndex)
          │
          │  _ingest_to_kb()
          │   ├─ Step 1: ChromaDB (语义分块, teaching_summary)
          │   └─ Step 2: DT LlamaIndex (.txt upload, 追加不覆盖)
          │
route ∈ {"text_extract"}             ──→ 仅 ChromaDB
          │   (DT 已有完整文本，不重复写入)
          │
route == "passthrough"               ──→ 跳过 (无有效可索引内容)
```

---

## 4. ChromaDB 存储层

### 集合命名规则

**实现**: `_chromadb_kb_name()` — `provider_api.py:809-829`

```
规则:
  1. 纯 ASCII [a-zA-Z0-9._-] → 直接使用
  2. 含中文/非ASCII → sha256(name)[:8] → base64url → 拼接前缀

示例:
  "初中教材"  →  "初中教材_Zu4F3wD-a-s"
  "math-calc" →  "math-calc"
```

### 文档 ID 确定性策略

```python
# 全量双写路径 (_ingest_to_kb)
import hashlib
_content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
ids = [f"{_content_hash}_{i}" for i in range(len(docs))]

# 仅 ChromaDB 路径 (_maybe_ingest_result → else branch)
_content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
ids = [f"{_content_hash}_{i}" for i in range(len(docs))]
```

**效果**: 同一份内容多次上传 → 同一组 ID → ChromaDB `upsert` 自动覆盖，不产生重复。

### 语义分块策略

**实现**: `_split_content_for_ingest()` — `provider_api.py`

- 按 Markdown 标题/自然段边界分割
- 每块 500-2000 字符
- 保留上下文窗口 overlap

### 教学摘要 (v3)

**实现**: `_generate_teaching_summary()` — `provider_api.py:2420`

- 对 OCR/提取的原始文本，异步调用 DeepSeek API 生成教学摘要
- 摘要包含: 知识点提炼、考试章节定位、教育价值评估
- 入库时优先使用摘要，失败回退到原始文本
- `type` metadata 标记: `"teaching_summary"` 或 `"raw_ocr"`

---

## 5. DT LlamaIndex 同步策略

### 条件触发

DT LlamaIndex 同步**仅在** `needs_dt_sync = True` 时执行：

```python
needs_dt_sync = route in ("ocr", "document_extract")
```

**原因**: 文字层 PDF / Office / 文本文件已在 DT 的 LlamaIndex 构建时有完整文本层，无需重复写入。

### 写入方式

**实现**: `_ingest_to_kb()` Step 2 — `provider_api.py:2241-2310`

1. 将提取后的文本写入临时 `.txt` 文件
2. `POST /api/v1/knowledge/{kb_name}/upload` 上传到 DT
3. 文件名: `{原文件名}.txt`（追加 `.txt` 后缀，不覆盖原始 PDF）

**关键约束**: 已存在文件会触发 409 → 自动重试时跳过：

```python
if resp.status_code == 409:
    logger.info("DT index sync: already indexed, skip")
    return
```

### 写回保护

| 保护措施 | 机制 |
|---------|------|
| KB 存在性检查 | 每次入库前调用 `_check_kb_exists_on_dt()` |
| 文件名冲突 | 追加 `.txt` 后缀，与原始 PDF 共存 |
| 重复上传 | DT 409 检测 → 跳过不覆盖 |
| 仅 ChromaDB 路径 | 跳过 DT 同步，不重复 |

---

## 6. Sidecar 富化时序

### 触发机制

**实现**: `_spawn_unified_pipeline_bg()` → `_run_unified_pipeline_bg()` — `provider_api.py:1115-1210`

- **异步 fire-and-forget** — 不阻塞主请求响应
- **去重 guard** — 同一文件 hash 正在处理中时跳过 (`_UNIFIED_PIPELINE_STATUS`)
- **并发 gate** — `asyncio.Semaphore(1)` 保证 LLM 不被打爆
- **超时保护** — `asyncio.wait_for(_run(), timeout=1800)` (30 min)

### 产物

| Sidecar | 适用类型 | 内容 |
|---------|---------|------|
| `{filename}.txt` | 所有 | 纯文本提取 (与 _handle_inbound_file 产物一致) |
| `{filename}.exam.json` | EXAM_PDF 仅 | 结构化试卷 (题目、选项、答案、知识点、配图) → see `exam_structurer.py` |
| `{filename}.figures/` | EXAM_PDF 仅 | 裁剪的配图 PNG (每张图一个文件) |

### 时序

```
主请求 (同步, ~3-15s)
  ├─ _handle_inbound_file() → extract_text() → 返回 OCR/提取结果
  ├─ _maybe_ingest_result() → ChromaDB + DT 写入
  └─ _spawn_unified_pipeline_bg() ...... 发出 sidecar 任务 (异步)

后台 (异步, ~10-600s)
  └─ _run_unified_pipeline_bg()
       ├─ UnifiedDocumentPipeline.process()
       │    ├─ classify_file()
       │    ├─ 按类型提取 (可复用的 OCR 结果)
       │    └─ 写出 .txt sidecar
       ├─ 如 exam_pdf → run_exam_pipeline()
       │    ├─ Phase 1: PaperLayoutEngine (布局分析)
       │    ├─ Phase 2: BlockOCREngine (块级 OCR)
       │    ├─ Phase 3: ExamStructurer (语义结构化)
       │    └─ Phase 4: 序列化 .exam.json + .figures/
       └─ 记录状态到 _UNIFIED_PIPELINE_STATUS

后续 (未来补全)
  └─ _enrich_with_sidecar_content() ← 消费 sidecar 重新入库更丰富的索引
```

---

## 7. Metadata Schema

### ChromaDB Metadata (全量入库)

```jsonc
{
  "filename": "初三化学考试题.doc",       // 原始文件名
  "learner_id": "o9cq802CIb...@im.wechat", // 学习者 ID (WeChat 或 "web")
  "source": "mcp",                         // 入口来源: mcp | web_ui | web | web_ui_reindex | wechat | api
  "trace_id": "d77e651d-0027",             // 请求追踪 ID
  "type": "teaching_summary",              // 内容类型: teaching_summary | raw_ocr
  "subject": "chemistry",                  // 自动检测: math | chemistry | physics | ...
  "grade": "middle",                       // 自动检测: primary_low | primary_high | middle | ""
  "kb_name": "初中教材"                    // 知识库名称 (原始中文)
}
```

### Subject 检测规则

**实现**: `_detect_exam_subject()` — `provider_api.py`

通过关键词匹配自动判定学科：
- `math`: 数学/方程/几何/代数/函数/三角…
- `chemistry`: 化学/元素/反应/分子/原子/溶液…
- `physics`: 物理/力学/电/磁/光/热/运动…

### Grade 检测规则

**实现**: `_infer_grade()` — `provider_api.py:2158`

通过年级关键词匹配：
- `primary_low`: 一年级~三年级
- `primary_high`: 四年级~六年级
- `middle`: 初一~初三 / 七年级~九年级

### DT LlamaIndex Metadata (仅双写路径)

```python
# 文件上传到 DT 时，文件名追加 .txt
dt_filename = f"{original_filename}.txt"
# 内容: 教学摘要 (如有) 或原始 OCR 文本
```

---

## 8. 并发安全与并发控制

| 控制点 | 机制 | 位置 |
|--------|------|------|
| **文件处理去重** | `_FILE_PROCESS_CACHE` SHA256 LRU, 30min TTL | `_handle_inbound_file()` |
| **Per-learner 串行** | HA `_running_teachings` set guard | `weixin.py` |
| **LLM 全局串行** | `_llm_lock (_TTLock, ttl=120s)` | `_tutor_chat_core()` |
| **OCR 并发限制** | `asyncio.Semaphore(1)` | `ocr_adapters.py` |
| **Unified Pipeline** | `asyncio.Semaphore(1)` + 文件 hash 去重 | `_run_unified_pipeline_bg()` |
| **文件校验** | `_validate_file()` 扩展名 + 大小 (100MB) | 所有入口 |
| **KB 存在性** | `_check_kb_exists_on_dt()` HTTP 探活 | 所有入库路径 |

---

## 9. 补充资料：现有文档

| 文档 | 内容 |
|------|------|
| `docs/unified-document-pipeline.md` | 统一提取层 `extract_text()` 详细走线、MiniCPM-V 手动 OCR 管线、OpenCV 预处理、语义分块 |
| `patches/deeptutor-guided-teaching.patch` | 知识图谱提取器 + `kb_lookup_concept` / `kb_syllabus` 工具注册 |
| `tutor_platform/rag/` | 提取器、分类器、OCR 适配器、布局引擎、考题结构化器 |
| `docker/platform/provider_api.py` | 全部 API 端点 + `_handle_inbound_file()` + `_maybe_ingest_result()` |
| `vendor/hermes-agent/gateway/platforms/weixin.py` | WeChat 文件处理 + `_run_teaching_flow()` |

---

> **变更日志**
>
> | 日期 | 变更 |
> |------|------|
> | 2026-06-05 | v1.0 初版 — 完整入口矩阵 + 格式-索引决策表 + ChromaDB/DT 双存储规范 |
