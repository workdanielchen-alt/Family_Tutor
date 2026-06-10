# DeepTutor 系统架构文档

> 本文档基于当前代码实现，反映真实运行时的系统架构、组件关系和核心流程。

---

## 架构原则

1. **本地 LLM 优先，云端 LLM 兜底** — 每次教学调用优先尝试本地 NPU（rkllama），若 NPU 被 OCR 占用，平台透明切换 DT 到云端 DeepSeek API，用户无感知。

2. **Hermes Agent 为中枢，DT 为教学工具** — Hermes Agent (HA) 是系统中枢，接收所有微信消息并路由到对应后端（教学 → platform → DT，闲聊 → LLM）。DT 是 HA 调用的教学引擎，无独立用户入口。

3. **微信为首要入口，DT Web UI 为补充** — 日常学习通过微信进行（拍作业照片、获取引导、即时反馈）。Web UI (3782) 支持深度学习（集中复习、强化练习、知识库管理）。

4. **微信会话必须保证实时性** — iLink 长轮询约 5 分钟过期，所有后台处理（OCR、LLM 推理、教学生成）必须在窗口内完成。

5. **DT 与 HA 的 LLM 资源竞争必须最优化** — 两者共用本地 NPU，全局 `asyncio.Lock` 序列化访问，差异化超时策略：DT 短超时（5s）保持教学交互性，HA 长超时（300s）支持批量 OCR。

---

## 硬件规格

| 组件 | 规格 | 角色 |
|------|------|------|
| SoC | Rockchip RK3576 (4×Cortex-A76 + 4×Cortex-A55) | CPU + NPU (6 TOPS) |
| RAM | 8GB LPDDR4X | 共享 CPU/GPU/NPU 内存 |
| 启动 | 16GB eMMC | OS + 内核 |
| 存储 | 256GB SSD | Docker 镜像、容器、用户数据 |

---

## 容器架构

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Docker Network                                  │
│                   deepseek_deeptutor-network                            │
│                                                                         │
│  ┌──────────────────┐              ┌──────────────────────┐             │
│  │    微信(家长/孩子) │              │  DT Web UI (3782)    │             │
│  │    首要入口        │              │  深度学习补充入口     │             │
│  └────────┬─────────┘              └──────────────────────┘             │
│           │ iLink 长轮询                                               │
│           ▼                                                            │
│  ┌──────────────────────────────────────┐                              │
│  │         hermes_agent (8004)           │                              │
│  │  ┌─────────────────────────────────┐  │                              │
│  │  │  父网关 (parent bot)             │  │                              │
│  │  │  WEIXIN_TOKEN, 管理员权限        │  │                              │
│  │  └──────────────┬──────────────────┘  │                              │
│  │  ┌──────────────┴──────────────────┐  │                              │
│  │  │  子网关 (child bot)              │  │                              │
│  │  │  CHILD_WEIXIN_TOKEN, 学生权限    │  │                              │
│  │  └─────────────────────────────────┘  │                              │
│  │  ◆ 双网关 iLink 网关                │                              │
│  │  ◆ 家长/孩子双机器人身份             │                              │
│  │  ◆ 消息分类: OCR/教学/闲聊/设备      │                              │
│  │  ◆ teaching_sessions 会话管理        │                              │
│  │  ◆ 通知文件消费 (按 target 路由)      │                              │
│  └──────────────────┬───────────────────┘                              │
│                     │ HTTP REST                                        │
│                     ▼                                                  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                   platform (8100/8101)                            │  │
│  │                                                                   │  │
│  │  ┌──────────── Provider API (8100) ────────────┐                 │  │
│  │  │  /api/tutor/chat     → DT WebSocket 教学    │                 │  │
│  │  │  /api/teach/start    → 教学会话创建          │                 │  │
│  │  │  /api/teach/continue → 教学会话续接          │                 │  │
│  │  │  /api/process/file   → OCR + 自动教学        │                 │  │
│  │  │  /api/ocr            → 纯 OCR               │                 │  │
│  │  │  /api/vision         → 视觉理解             │                 │  │
│  │  │  /api/solve          → 深度解题             │                 │  │
│  │  │  /api/kb/search      → ChromaDB 文本搜索     │                 │  │
│  │  │  /api/kb/figures/*   → 图形搜索/查看        │                 │  │
│  │  │  /api/kb/ingest-file → 知识库文件入库        │                 │  │
│  │  │  /api/kb/sync-from-dt→ DT→ChromaDB 同步    │                 │  │
│  │  │  /api/ingest/*       → 多入口文件入库        │                 │  │
│  │  │  /api/mastery/*      → 掌握度 CRUD          │                 │  │
│  │  │  /api/practice/*     → 练习/试卷生成        │                 │  │
│  │  │  /api/report/*       → 学习报告             │                 │  │
│  │  │  /api/llm/acquire    → LLM 锁获取           │                 │  │
│  │  │  /api/llm/release    → LLM 锁释放           │                 │  │
│  │  │  /api/tasks/*        → 统一任务系统         │                 │  │
│  │  │  /api/bot/*          → 微信二维码/绑定      │                 │  │
│  │  │  /health             → 健康检查             │                 │  │
│  │  └────────────────────────────────────────────┘                 │  │
│  │                                                                   │  │
│  │  ┌───────── MCP Server (同进程 ASGI) ──────────┐                 │  │
│  │  │  33+ 工具: kb_search, tutor_chat,           │                 │  │
│  │  │  process_file, deep_solve, wifi_configure,  │                 │  │
│  │  │  device_status, generate_exam_paper, ...    │                 │  │
│  │  │  ◆ 熔断器 (Circuit Breaker) 3次失败→切换    │                 │  │
│  │  │  ◆ 场景管理 (practice/reading/full)         │                 │  │
│  │  │  ◆ 角色权限 (家长/孩子工具门禁)             │                 │  │
│  │  └────────────────────────────────────────────┘                 │  │
│  │                                                                   │  │
│  │  ┌──────── Device Manager (8101) ─────────────┐                 │  │
│  │  │  /api/device/status   → CPU/内存/温度       │                 │  │
│  │  │  /api/device/storage  → 存储空间            │                 │  │
│  │  │  /api/device/ssd      → SSD 健康            │                 │  │
│  │  │  /api/device/wifi/*   → WiFi 扫描/连接      │                 │  │
│  │  │  /api/device/cleanup  → 清理临时文件         │                 │  │
│  │  └────────────────────────────────────────────┘                 │  │
│  │                                                                   │  │
│  │  ┌──────── 内嵌 ChromaDB (PersistentClient) ───┐                 │  │
│  │  │  kb_Zu4F3wD-a-s          — 文本向量 (bge-small-zh-v1.5)     │  │
│  │  │  kb_Zu4F3wD-a-s_figures  — 图形描述向量                     │  │
│  │  │  curriculum               — 课标知识点 (KP-level)            │  │
│  │  │  ◆ 嵌入: BAAI/bge-small-zh-v1.5 (512D, ONNX)               │  │
│  │  │  ◆ 磁盘: /data/chromadb                                     │  │
│  │  └────────────────────────────────────────────────────────────┘ │  │
│  │                                                                   │  │
│  │  tutor_platform/ (Python 模块):                                   │  │
│  │    unified_provider.py  — ChromaDB 单例封装 (add/query/figures)   │  │
│  │    teach_loop.py        — Agentic Loop 教学引擎 (THINK→TOOL→…)   │  │
│  │    teach_session.py     — 教学会话持久化 (试题/进度/掌握度)       │  │
│  │    teach_question.py    — 试题数据模型                            │  │
│  │    teach_tools.py       — 教学工具 (知识库搜索/图形匹配)          │  │
│  │    ingest_status.py     — 入库状态追踪                            │  │
│  │    report_scheduler.py  — 报告调度                                │  │
│  │    report_push.py       — 报告格式化                              │  │
│  │    ha_client.py         — HA API 客户端                           │  │
│  │    quiz_sync.py         — 答题记录同步                            │  │
│  │    rag/extractors.py    — 文本/图形提取统一入口                   │  │
│  │    rag/figure_types.py  — UnifiedFigure 数据模型                  │  │
│  │    rag/rapid_ocr.py     — RapidOCR (PP-OCRv4) 封装                │  │
│  │    rag/ocr_adapters.py  — Qwen2-VL OCR 适配器                     │  │
│  │    tools/embeddings.py  — Embedding 函数 (bge-small-zh-v1.5)      │  │
│  │    tools/preprocess.py  — 图片预处理                              │  │
│  └──────────────────┬────────────────────────────────────────────────┘  │
│                     │                                                  │
│            ┌────────┼────────┬─────────────┐                           │
│            ▼        ▼        ▼             ▼                           │
│  ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐            │
│  │  rkllama   │ │ deeptutor│ │ qwen2vl  │ │  Domains     │            │
│  │  (8080)    │ │(8001/3782│ │ (8081)   │ │  (共享模块)   │            │
│  │ NPU LLM    │ │ 教学引擎  │ │ OCR 引擎  │ │              │            │
│  │            │ │           │ │           │ │ tutoring/    │            │
│  │ r1-distill │ │ AgentLoop │ │ Qwen2-VL  │ │  mastery.py  │            │
│  │ deepseekocr│ │ TutorBot  │ │ 2B-Instruct│ │  掌握度追踪  │            │
│  │ qwen3-vl   │ │ FastAPI   │ │ llama.cpp │ │  错题本      │            │
│  │ bge-m3     │ │ Next.js   │ │           │ │  每日统计    │            │
│  │ (可选NPU)  │ │ 多用户    │ │           │ │  Ebbinghaus  │            │
│  └────────────┘ └──────────┘ └──────────┘ └──────────────┘            │
│                                                                         │
│  图例:                                                                  │
│    ───→ HTTP / REST API                                                │
│    ───→ iLink 长轮询 (微信)                                            │
│    ───→ 本地 NPU/CPU 调用                                              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 端口映射

| 端口 | 容器 | 用途 |
|------|------|------|
| 8004 | hermes_agent | WeChat 双网关 API — **首要用户入口** |
| 3782 | deeptutor | 前端 Web UI — **深度学习补充入口** |
| 8001 | deeptutor | 后端 API (FastAPI + WebSocket) — 内部 |
| 8080 | rkllama | OpenAI 兼容 NPU LLM API — 内部 (可选) |
| 8081 | qwen2vl | Qwen2-VL llama.cpp OCR 服务 — 内部 |
| 8100 | platform | Provider API + MCP Server — 内部 |
| 8101 | platform | Device Manager — 内部 |

端口 8004 对外开放给微信，其余均为 Docker 网络内部端口。

---

## 组件详情

### 1. hermes_agent (8004) — 系统中枢 / 首要入口

微信 iLink 双网关。**中央协调器**：接收所有微信消息，分类后路由到对应后端。

**双网关架构：**
- **父网关** — 管理员权限 (WEIXIN_TOKEN)，可访问所有功能
- **子网关** — 学生权限 (CHILD_WEIXIN_TOKEN)，受限的教学交互

**核心机制 (HERMES PATCH 区域)：**

| 机制 | 角色 |
|------|------|
| `_teaching_sessions` dict | 跟踪活跃教学会话 (30min TTL) |
| `_auto_process_media` | 拦截图片 → platform OCR + 教学 |
| `_auto_teaching_followup` | 学生文字回复路由到 DT (非本地 LLM) |
| `_consume_report_notifications` | 后台任务 (30s 轮询) 消费通知文件, 按 target 字段路由 (parent→父网关, child→子网关) |
| `_process_message` | 主分发: 媒体→OCR, 文字→教学/闲聊 |

**教学会话生命周期：**
1. 学生发图片 → `_auto_process_media` → POST /api/process/file → OCR + DT 教学 → 会话创建
2. 学生回复文字 → `_auto_teaching_followup` → POST /api/tutor/chat → DT 评估 + 下一题
3. 解析 DT 回复中的答案评估标记 → 更新掌握度 → 自动触发练习或试卷
4. 30分钟无活动 → 会话过期 → 恢复正常聊天

---

### 2. platform (8100/8101) — 编排层 / MCP / KB / 教学引擎

编排层和 **LLM 调度器** (原则 1)。接收 HA 请求，协调 OCR、LLM 调度、教学、知识库。

#### LLM 资源锁

`_llm_lock` (`_TTLock`, TTL=120s) 序列化本地 NPU 访问，带超时自动恢复机制：

| 场景 | 超时 | 结果 |
|------|------|------|
| DT 教学，锁空闲 | 5s | 获取 → 切 DT 到 rkllama 配置 → 本地 NPU 教学 |
| DT 教学，锁被占 | 5s 超时 | 切 DT 到 deepseek 配置 → 云端 API 教学 |
| HA OCR，锁空闲 | 60s | 获取 → OCR → 释放 |
| HA OCR，锁被占 | 60s | 等待 (DT 教学通常 30-60s 完成) |

#### MCP Server (同进程 ASGI 合并)

Phase B 合并：MCP Server 作为 ASGI middleware 内嵌在 platform 进程中，通过 `httpx.ASGITransport` 直接调用本进程 API，无网络开销。

**33+ MCP 工具分类：**

| 类别 | 工具 | 数量 |
|------|------|------|
| 教学 | tutor_chat, teach_start, teach_continue, practice_generate | 4 |
| 知识库 | kb_search, kb_ingest, kb_sync | 3 |
| OCR/视觉 | process_file, ocr, vision, vision_solve | 4 |
| 解题 | solve, deep_solve | 2 |
| 掌握度 | mastery_overview, mastery_detail, wrong_answers | 3 |
| 报告 | daily_report, weekly_report, monthly_report | 3 |
| 设备管理 | device_status, wifi_connect, wifi_scan, cleanup | 4 |
| 场景管理 | set_scene, detect_scene | 2 |
| 其他 | circuit_reset, get_circuit_status, list_learners | 3+ |

**熔断器 (Circuit Breaker)：** 每个后端独立计数，3 次连续失败 → circuit open → 30s 冷却后 half-open → 成功则恢复。

---

#### 知识库 (KB) 子系统

**双索引模型：**

| 索引层 | 位置 | 引擎 | 嵌入模型 | 用途 |
|--------|------|------|----------|------|
| DT LlamaIndex | deeptutor 容器 `/app/data/knowledge_bases/` | llama_index | ollama bge-small-zh-v1.5 | 教材文档索引 (Web UI 管理) |
| platform ChromaDB | platform 容器 `/data/chromadb/` | chromadb PersistentClient | BAAI/bge-small-zh-v1.5 (ONNX) | 文本 + 图形向量检索 (教学时查询) |

DT LlamaIndex 由 Web UI 管理（创建/删除/上传），platform 不直接操作。platform 通过 `_sync_kb_from_dt` 定期从 DT 同步文本到 ChromaDB，形成可检索的副本。

**ChromaDB 集合：**

| 集合名 | 内容 | 维度 | 条数 |
|--------|------|------|------|
| `kb_Zu4F3wD-a-s` | 文本 chunks (教材 + 用户上传) | 512 | ~2,816 |
| `kb_Zu4F3wD-a-s_figures` | 图形描述 | 512 | ~1,426 |
| `curriculum` | 课标知识点 (KP-level) | 512 | ~298 |

**命名规则：** 中文 KB 名 (`初中教材`) → `_chromadb_kb_name()` → `kb_Zu4F3wD-a-s` → 图形集合 `{sanitized_name}_figures` = `kb_Zu4F3wD-a-s_figures`。存储和查询使用相同的 `_sanitize_collection_name()` 确保一致性。

**KB 生命周期：**

```
Web UI 创建 KB (Settings → Knowledge Bases)
    → DT LlamaIndex 索引初始化
    → 上传教材 PDF
        → DT 文本提取 + 向量索引
        → Web UI 回调 POST /api/kb/ingest-file → platform ChromaDB 同步
            → 文本提取 (_handle_inbound_file)
            → ChromaDB 入库 (_ingest_to_kb)
            → 图形提取 (_store_figures_from_file)
        → POST /api/kb/sync-from-dt → 一键全量同步 (Web UI 触发)
```

**入库入口与防护：**

| 端点 | 入口 | 防护 |
|------|------|------|
| `/api/kb/ingest-file` | Web UI KB上传 | `_check_kb_exists_on_dt` + `_reject_suspicious_filename` |
| `/api/kb/sync-from-dt` | Web UI 一键同步 | `_SIDECAR_SUFFIXES` 过滤侧车文件 |
| `/api/ingest/proxy/{kb_name}` | Web 代理上传 | `_check_kb_exists_on_dt` + `_reject_suspicious_filename` |
| `/api/ingest/file` | MCP 显式入库 | `_check_kb_exists_on_dt` (via `_maybe_ingest_result`) |
| `/api/ingest/text` | API 文本入库 | `_check_kb_exists_on_dt` |
| `/api/process/file` (非微信) | MCP 处理 | `kb_name` 非空 + `_check_kb_exists_on_dt` |
| `/api/process/file` (微信) | 教学照片 | ❌ `suppress_auto_teach=1` 跳过入库 |

**三道 KB 卫生防护：**

| # | 位置 | 防护 |
|---|------|------|
| ① | `_sync_kb_from_dt` | 过滤 11 种侧车后缀 (`.pdf.txt`, `.docx.txt`, `.pptx.txt`, `.png.txt`, `.htm.txt`…) |
| ② | `api_kb_ingest_file` / `api_ingest_proxy` | `_reject_suspicious_filename` 拒绝 `test*`/`tmp*`/`sample*`/`demo*` 前缀 + <50B 非文本文件 |
| ③ | `_maybe_ingest_result` | `_check_kb_exists_on_dt` — KB 不存在直接拒绝 |

#### 图形管道

**提取与入库：**

```
教材 PDF 上传
    → _store_figures_from_file(file_path, kb_name)
        → extract_figures(pdf, llm_client=None)
            → extract_pdf_embedded_images() (PyMuPDF, skip前15页, 最多60张)
            → RapidOCR (PP-OCRv4) 提取图中文字
        → 保存 PNG → <pdf_stem>.figures/<figure_id>.png
        → 保存索引 → <pdf_stem>.figures/_index.json
        → 描述富化: "教材：义务教育教科书·化学九年级上册；图中文字：{OCR}"
        → add_figures() → ChromaDB kb_Zu4F3wD-a-s_figures
```

**富化策略：** RapidOCR 从教材嵌入图片提取的文字通常极短（"口"/"1"/"H"/"玻璃片"），嵌入向量与长考试文本的余弦距离天然在 1.0-1.4 之间。在描述前拼接 `"教材：{教科书名称}"` 后，距离降至 0.5-0.7，使 bge-small-zh-v1.5 能将其与学科查询关联。

**教学时检索：**

```
_build_teaching_persona(context)
    → provider.query(kb_name, [exam_text], n_results=10, include_figures=True)
        → 文本查询 kb_Zu4F3wD-a-s (主查询)
        → 图形查询 kb_Zu4F3wD-a-s_figures (并行，distance < 1.3)
        → 图形合并到文本结果的 figures 字段
    → Persona 注入: "### 相关知识库参考" + "### 相关图形" (Markdown img 标签)
    → _last_teaching_figures 缓存 (供 _tutor_chat_core 后处理追加到回复末尾)
```

**距离阈值 `1.3`：** bge-small-zh-v1.5 的余弦空间里，长文本 (800 字考试题) 与短文本 (10 字教材名+OCR) 的相似度天然较低。`0.8` 阈值会过滤掉几乎所有图形，`1.3` 保留教材名匹配的同时拒绝完全无关的图形。

#### 学科检测

检测优先级链：

```
1. 调用者显式传入 subject 参数
2. _subject_from_filename(filename)  ← 从教材文件名推断 (最可靠)
      "义务教育教科书·化学九年级上册.pdf" → "chemistry"
      "义务教育教科书·数学七年级下册.pdf" → "math"
3. _detect_exam_subject(content)  ← 关键词匹配 (考试/OCR 文本兜底)
```

文件名推断避免了 chemistry 关键词（"反应"/"元素"/"分解"）错误匹配数学/物理文本的问题。此前 1,979 条教材 chunks 被错误标记为 `chemistry`。

#### 教学引擎 (Agentic Loop)

教学从简单的 DT WebSocket 代理演进为多阶段 Agentic Loop：

```
_tutor_chat_core(phase="FIRST_QUESTION" | "EVALUATE_ANSWER")
    ├── _build_teaching_persona() → 构建含 KB/课标/错题/复习的完整 persona
    ├── _update_soul_with_context() → PATCH SOUL.md (教学规则注入 DT)
    └── run_teach_loop_from_args() (AGENTIC_LOOP_ENABLED=true)
         ├── Phase: Plan → 分析学生状态, 选择教学策略
         ├── Phase: Solve → 生成题目/评估答案 (THINK→TOOL→FINISH 标签协议)
         │    ├── THINK 思考过程
         │    ├── TOOL 工具调用 (kb_search, mastery_query 等)
         │    └── FINISH 最终输出 (题目或评价)
         └── Phase: Review → 知识点回顾, 掌握度更新
```

**关键模块：**
- `teach_loop.py` — 多阶段教学管道引擎
- `teach_session.py` — 教学会话持久化 (OCR 试题提取、进度追踪、答案历史)
- `teach_question.py` — 试题数据模型 (内容/选项/答案/解析/提示)
- `teach_tools.py` — 教学工具集 (知识库搜索、图形匹配、掌握度查询)

#### 教学会话 (TeachSession) 系统

将临时 OCR 题目转化为持久化教学会话：

```
/api/teach/start → TeachSession.create(learner_id, ocr_text, title, task_type)
    → _pre_extract_exam() 从 OCR 文本预提取试题 → _extracted_exams 缓存
    → _tutor_chat_core(phase="FIRST_QUESTION") → 教学开始

/api/teach/continue → TeachSession.recover(session_id)
    → 从中断处继续 (支持容器重启恢复)
    → _tutor_chat_core(phase="EVALUATE_ANSWER") → 评估 + 下一题
```

#### 统一任务系统

将教学、练习、试卷等异步任务统一管理：

```
POST /api/tasks/create
    body: {type: "teaching"|"practice"|"exam", payload: {...}}
    → 创建 TeachSession + 返回 task_id
    → 后台异步执行 (不阻塞 HTTP 响应)

GET /api/tasks/{session_id}/progress
    → 查询任务进度 (当前题号/总题数/状态)

POST /api/tasks/{session_id}/progress
    → 更新任务进度 (答题后上报)
```

#### 课标索引

知识点级别的课程大纲索引，用于教学时精准匹配章节：

```
_ensure_curriculum_indexed()
    → domains/curriculum/ 加载各科课标 YAML
    → 逐 KP 索引到 ChromaDB "curriculum" 集合
    → metadata: {type: "kp", subject, grade, semester, chapter, kp_id, importance}

_build_teaching_persona()
    → provider.query("curriculum", [exam_text], n_results=3)
    → 注入: "### 相关课程章节" + kp_id 标记
```

---

### 3. deeptutor (8001/3782) — 教学工具 / 深度学习 UI

HA 通过 platform 调用的专业教学引擎。Web UI (3782) 提供深度学习补充入口。

**核心能力：**
- `TutorBot` — 苏格拉底式教学 Agent，每次交互读取 SOUL.md
- WebSocket `/api/v1/tutorbot/teacher/ws` — 实时教学 (仅 platform 调用)
- AgentLoop 按 catalog 配置直接调用 LLM
- 知识库管理 UI (上传/搜索/图形浏览)

**模型 Catalog：**

| 配置 | 模型 | 端点 |
|------|------|------|
| `deepseek` | deepseek-v4-flash | `https://api.deepseek.com/v1` |
| `rkllama` | r1-distill-1.5b | `http://rkllama:8080/v1` |

Platform 在每次 WS 教学前切换配置。DT 无锁意识——只按 catalog 调用。

---

### 4. qwen2vl (8081) — OCR 引擎

Qwen2-VL-2B-Instruct 通过 llama.cpp 运行，提供 OpenAI 兼容的 vision API。

**部署方式：**
- 模型: `Qwen2-VL-2B-Instruct-Q4_K_M.gguf` + `mmproj-Qwen2-VL-2B-Instruct-Q8_0.gguf`
- 内存: 6GB 限制, `--mlock --no-mmap` 防 OOM
- Flash Attention: 开启
- 并发: `-np 1` (单请求处理)

**调用路径：**
- OCR: `_ocr_pixmap_bytes()` → RapidOCR 快速路径 → 公式检测 → Qwen2-VL 兜底
- 视觉描述: `POST /v1/chat/completions` → `model: "qwen2-vl"` → image_url base64

---

### 5. rkllama (8080) — 可选 NPU LLM

RK3576 NPU 本地推理服务。非生产必需（环境变量 `RKLLM_STUB_MODE=true` 时可跳过）。

**可用模型：**

| 模型 | 参数量 | 类型 | RAM | 加载 |
|------|--------|------|-----|------|
| r1-distill-1.5b | 1.5B | text | 591 MB | 常驻 |
| deepseekocr-3b | 3B | OCR | 1.8 GB | 惰性 |
| qwen3-vl-2b | 2B | vision | 1.1 GB | 惰性 |
| bge-m3 | — | embedding | — | — |

非文本模型惰性加载以节省内存。平台通过 `_llm_lock` 序列化访问，教学超时 5s → 自动降级 DeepSeek 云端。

---

## 数据流

### 教学流程

```
微信图片 ──→ hermes_agent (系统中枢)
                  │
                  ├─ _auto_process_media()
                  │    │
                  │    ├─ POST /api/llm/acquire?timeout=60s
                  │    │    ├─ 成功 → 持有锁做 OCR
                  │    │    └─ 失败 → OCR 跳过 (罕见)
                  │    │
                  │    ├─ POST /api/process/file (auto_teach=true)
                  │    │    │
                  │    │    ├─ OpenCV 预处理 → OCR
                  │    │    │    ├─ rkllama (生产 RK3576 NPU)
                  │    │    │    └─ Qwen2-VL (llama.cpp 推理)
                  │    │    │
                  │    │    ├─ OCR 结果检查
                  │    │    │    ├─ 有内容 → 入库 + 缓存上下文
                  │    │    │    └─ 空/乱码 → route=ocr_fallback
                  │    │    │
                  │    │    └─ auto_teach_effective → 异步教学
                  │    │
                  │    └─ 释放 LLM 锁
                  │
                  ├─ 即时确认: "📝 收到题目，正在识别处理，请稍候..."
                  │
                  └─ 后台 30s 轮询: _consume_report_notifications()
                       → tutor_reply 文件 → self.send() → 微信用户

微信文字 ──→ hermes_agent
                  └─ _auto_teaching_followup()
                       └─ POST /api/tutor/chat → _tutor_chat_core()
```

### SOUL.md 注入 (每次教学前)

```
_update_soul_with_context()
    ├─ _build_teaching_persona() → 组装完整 persona:
    │    ├─ 教师基础人格 (_TEACHER_SOUL / _TEACHER_EXPLAIN_SOUL)
    │    ├─ 年龄适配指令 (小学低/高年级, 初中)
    │    ├─ 当前教学内容 (OCR 提取的题目)
    │    ├─ 相关知识库参考 (ChromaDB 查询 top 3, subject 过滤)
    │    ├─ 相关图形 (ChromaDB figures 查询, Markdown img 标签)
    │    ├─ 课标章节 (curriculum 集合查询)
    │    ├─ 到期复习 (Ebbinghaus)
    │    ├─ 薄弱知识点 + 近期错题
    │    └─ 自动生成的试卷 (pending exam context)
    ├─ _last_persona 缓存比对 → 未变更跳过 PATCH
    └─ _patch_soul(): GET → PATCH/POST+PUT → DT SOUL.md
```

### 定期任务 (platform 后台 60s tick)

```
_periodic_task_loop()
    ├─ sync_quiz_to_mastery() (每 300s)
    ├─ report_scheduler.py
    │    ├─ push_daily_reports() (每天 20:00)
    │    ├─ push_weekly_reports() (周一 20:00)
    │    └─ push_monthly_reports() (每月 1 日 20:00)
    ├─ 强化试卷自动推送 (薄弱点 ≥3, 24h 冷却)
    └─ HA _consume_report_notifications() 消费通知文件
```

---

## 文件处理流水线

```
上传文件
    │
    ├─ 教学上传 (微信/Web Chat)
    │    ├─ suppress_auto_teach=1 / kb_name="" → 不入库, 仅 OCR + 教学
    │    └─ OCR 文本缓存到内存 → 直接进入教学流
    │
    ├─ 知识库入库 (Web UI / MCP)
    │    ├─ 闸门: _check_kb_exists_on_dt + _reject_suspicious_filename
    │    │
    │    ├─ _handle_inbound_file() → extract_text() (extractors.py 统一入口)
    │    │    ├─ 图片: OpenCV预处理 → VL模型OCR → 水平分割并行
    │    │    ├─ PDF: pymupdf4llm.to_markdown() → 扫描件Qwen2-VL OCR
    │    │    ├─ Office: python-docx/openpyxl/pptx → markitdown fallback
    │    │    └─ 文本: 多编码链 (utf-8→gbk→gb2312→latin-1)
    │    │
    │    ├─ 文本入库 (_ingest_to_kb)
    │    │    ├─ 学科检测: _subject_from_filename(filename) → _detect_exam_subject(content)
    │    │    ├─ 教学摘要生成 (非理科: LLM 摘要; 理科: 保留原始公式)
    │    │    ├─ ChromaDB: _split_content_for_ingest (800字 chunks) → add_documents
    │    │    └─ DT LlamaIndex: OCR 路径 → .txt 上传回 DT (双写)
    │    │
    │    ├─ 图形入库 (_store_figures_from_file)
    │    │    ├─ extract_figures(pdf, llm_client=None) → RapidOCR 提取嵌入图片
    │    │    ├─ 保存 PNGs → <pdf_stem>.figures/<figure_id>.png
    │    │    ├─ 描述富化: "教材：{教科书名}" + "；图中文字：{OCR}"
    │    │    ├─ 保存 _index.json
    │    │    └─ add_figures() → ChromaDB kb_{hash}_figures
    │    │
    │    └─ UnifiedDocumentPipeline (fire-and-forget 后台)
    │         ├─ classify_file() → 11 DocTypes
    │         ├─ Phase 1-4 考试结构化 (.exam.json sidecar)
    │         └─ _enrich_with_sidecar_content() 消费更完整的 sidecar
    │
    └─ DT 同步 (_sync_kb_from_dt)
         ├─ 列出 DT 知识库文件
         ├─ 过滤 _SIDECAR_SUFFIXES (跳过 .pdf.txt 等侧车)
         ├─ OCR checkpoint 去重 (embedded=true 跳过)
         └─ 逐文件下载 → OCR → ChromaDB 入库
```

---

## 微信实时性保障

| 措施 | 详情 |
|------|------|
| 教学超时 | DT WebSocket 响应预期 30s 内 |
| 锁超时 (DT) | 5s → 本地 NPU 忙则立即切换云端 |
| 锁超时 (HA) | 300s — OCR 可等待，用户看到"处理中" |
| 模型惰性加载 | OCR (1.8GB) 和视觉 (1.1GB) 按需加载 |
| OCR 预热 | 首次图片请求预热一次，持久化标记跳过后续预热 |
| OCR 并发控制 | `asyncio.Semaphore(2)` 防 NPU OOM |
| 会话保活 | HA 维护 iLink 心跳 |
| WS 连接复用 | `_DTTutorSession` 连接池，避免每次 2-5s 冷启动 |
| WS 空闲清理 | 每 5 分钟清理空闲 >30 分钟的会话 |
| 会话自动清理 | 每日凌晨 4-6 点发送 /new 防 OOM |
| 上下文持久化 | 磁盘 JSON 文件 + 启动恢复 |
| 本地 LLM 弱回复兜底 | 本地模型输出 < 20 字符时自动降级到云端 |

---

## 存储布局

```
宿主机路径                    容器路径                        用途
──────────                    ─────────────                  ───────
./data/user                  /app/data/user                  Model catalog, 用户设置
./data/memory                /app/data/memory                DT 记忆持久化
./data/knowledge_bases       /app/data/knowledge_bases       RAG 知识库
    └── 初中教材/raw/                                         教材 PDF 源文件
         ├─ *.pdf                                             18 本教材 (化学/数学/物理/语文)
         ├─ *.figures/                                        图形 PNG 目录
         │   └─ _index.json                                  图形元数据 (figure_id/描述/类型)
         └─ version-1/                                       LlamaIndex 向量索引
./data/mastery               /data/mastery                   学习者掌握度数据
./data/chromadb              /data/chromadb                  向量存储 (PersistentClient)
    └── ocr_checkpoints/                                      OCR 进度 checkpoint (防重启丢失)
./data/ingest_status         /data/ingest_status             文件入库追踪
./data/uploads               /data/uploads                   用户上传
./data/sources               /data/sources                   处理后归档
./data/quiz_sessions         /data/quiz_sessions             答题会话持久化
./data/teach_sessions        /data/teach_sessions            教学会话持久化
./data/hermes/notifications  /data/hermes/notifications      报告推送通知文件
./data_dev/hermes            /opt/data                       父网关数据
./data_dev/hermes_child      /opt/data/child                 子网关数据

代码挂载 (只读):
./docker/platform/provider_api.py   → /app/provider_api.py
./docker/platform/mcp_server.py     → /app/mcp_server.py
./tutor_platform/                   → /tutor_platform/
./vendor/hermes-agent/*             → /opt/hermes/
```

---

## 关键设计决策

1. **微信优先，Web 补充** — 日常学习通过微信完成，Web UI 仅用于深度学习和知识库管理

2. **HA 为系统中枢** — HA 拥有会话生命周期和路由逻辑，DT 是纯教学工具

3. **本地优先，透明降级** — 5s 锁超时后自动切换到云端，用户无感知

4. **差异化锁超时** — DT 5s 短超时保持交互性，HA 300s 长超时支持 OCR

5. **DT 直连 LLM，platform 控制路由** — DT AgentLoop 直接调用 LLM，platform 负责切换 catalog 配置

6. **SOUL.md 承载教学策略** — 所有教学规则在 SOUL.md，DT 每轮重新读取

7. **最小 HA 补丁** — 所有 HA 修改用 `==== HERMES PATCH` 标记包裹

8. **NPU 模型惰性加载** — 仅 text 模型常驻，OCR/vision 按需加载

9. **[ANSWER:correct|wrong] 评估标记** — DT 仅评估，platform 持久化

10. **DeepSeek API 直连** — 练习/试卷生成绕过 HA 代理，避免 502 错误

11. **通知文件桥** — `report_scheduler.py` 写文件 → HA 消费发送，解耦两个容器

12. **自动试卷 24h 冷却** — 防止过度推送，确保学习节奏自然

13. **Ebbinghaus 复习融入教学流** — 复习安排注入 SOUL.md，学习中自然复习

14. **MCP 合并到 platform 进程** — Phase B 同进程 ASGI，减少网络开销

15. **双网关 WeChat** — 父 + 子独立 iLink 会话，角色权限分离

16. **WS 连接池** — 按 learner 复用 WebSocket，避免每轮教学 2-5s 冷启动

17. **上下文磁盘持久化** — 容器重启后恢复教学上下文，从中断处继续

18. **教育与 OCR 并发控制** — `Semaphore(2)` 防止 NPU 内存溢出

19. **基于规则 + LLM 兜底的设备管理** — `device_command` 先规则匹配，未分类时 LLM 处理

20. **文件归档 trace_id 体系** — 所有上传文件以 `{trace_id}_{timestamp}_{filename}` 归档，支持 `view_source` 溯源

21. **通知目标路由** — `_write_notification(target="parent"/"child")` 配合 HA 双网关，报告推家长，强化试卷推孩子，文件桥解耦两容器

22. **后台 Periodic Loop** — `_periodic_task_loop()` 60s tick 模拟定时任务，文件 marker 追踪执行状态，无外部 cron 依赖

23. **图形与文本双索引** — 图形存入独立 `{kb}_figures` ChromaDB 集合，与文本分开查询。图形描述通过教材名富化（`"教材：{名称}"`）使短 OCR 文本可被 bge-small-zh-v1.5 语义匹配。宽松距离阈值 (1.3) 适配短描述 vs 长考试文本的余弦分布

24. **知识库只进不出** — 三道防护确保 KB 不被污染：API 入口拒收测试文件、同步时过滤侧车循环 (_SIDECAR_SUFFIXES)、写入前校验 KB 存在

25. **文件名优先学科检测** — 教材文件名推断学科远比 OCR 文本关键词可靠。chemistry 关键词（"反应"/"元素"/"分解"）会错误匹配数学/物理文本。优先链：显式参数 → 文件名 → 关键词

26. **Agentic Loop 多阶段教学** — Plan→Solve→Review 三阶段管道，THINK→TOOL→FINISH 标签协议。`teach_loop.py` 独立于 DT AgentLoop，在 platform 侧控制完整教学流程

27. **教学会话持久化** — TeachSession 将 OCR 试题提取、答题进度、掌握度变化持久化到磁盘 (`/data/teach_sessions/`)。容器重启后通过 `/api/teach/continue` 恢复，支持从中断处继续教学
