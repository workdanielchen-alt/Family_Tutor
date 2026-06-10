# K9 深度学习系统架构文档

> 版本: v2.0
> 日期: 2026-06-10
> 目标: 微信拍题 + Web 深度学习，系统性提高 K9 孩子学习成绩

---

## 一、整体架构

```
                         ┌──────────────────┐
                         │   用户入口         │
                         │ 微信拍照 / Web UI  │
                         └────────┬─────────┘
                                  │
                    ┌─────────────┴────────────────┐
                    │                              │
              ┌─────▼─────┐                  ┌─────▼─────┐
              │ 教学上传    │                  │ 知识库上传  │
              │ (微信/Web)  │                  │ (Web UI)   │
              │            │                  │            │
              │ suppress_  │                  │ KB 三道防护 │
              │ auto_teach │                  │  + 学科检测 │
              │ =1 不入库  │                  │            │
              └─────┬─────┘                  └─────┬─────┘
                    │                              │
              ┌─────▼─────┐                  ┌─────▼─────┐
              │ OCR 预处理  │                  │ 文件处理    │
              │ Qwen2-VL   │                  │ 文本提取    │
              └─────┬─────┘                  │ 图形提取    │
                    │                        │ (RapidOCR) │
              ┌─────▼─────┐                  └──┬──┬───┬──┘
              │ 结构化提取  │                    │  │   │
              │ DeepSeek   │              ┌─────▼──▼───▼──┐
              │ 题目+答案   │              │  ChromaDB 入库  │
              └─────┬─────┘              │  文本 + 图形    │
                    │                    │  (KB 集合)     │
              ┌─────▼─────┐              └────────────────┘
              │ Teach     │
              │ Session   │
              │ 持久化     │
              └─────┬─────┘
                    │
          ┌─────────┴──────────┐
          │                    │
    ┌─────▼─────┐        ┌─────▼─────┐
    │ Agentic   │        │ 直接 DT    │
    │ Loop 教学  │        │ WebSocket  │
    │ Plan→Solve│        │ 教学       │
    │ →Review   │        │            │
    └─────┬─────┘        └─────┬─────┘
          │                    │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │  _build_teaching_  │
          │  persona()         │
          │  KB参考 + 图形     │
          │  + 课标 + 错题     │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │  SOUL.md 注入      │
          │  → DT 每轮读取     │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │  逐题教学循环        │
          │  平台控流程          │
          │  + 平台判题          │
          └─────────┬──────────┘
                    │
          ┌─────────▼──────────┐
          │  掌握度 / 错题本    │
          │  mastery JSON       │
          └────────────────────┘
```

---

## 二、设计原则

1. **微信拍照为首要入口，Web UI 为深度学习补充** — 日常作业通过微信拍照完成 OCR + 自动教学。Web UI 支持知识库管理、深度学习、数据看板。

2. **教学上传与知识库入库隔离** — 微信拍照走 `suppress_auto_teach=1` 路径，OCR 后不写 ChromaDB。知识库上传（Web UI 教材）走专属入库管道，带三道卫生防护。

3. **平台控流程，DT 做教学** — 题号管理、判题、进度追踪由 platform 控制（`_tutor_chat_core` / `teach_loop.py`）。DT 专注引导式教学——接收 SOUL.md 中注入的完整教学 persona 后输出引导问题或答案评估。

4. **教学会话可中断可继续** — TeachSession 将 OCR 试题提取、答题进度、掌握度变化持久化到磁盘 (`/data/teach_sessions/`)。48h TTL，容器重启后通过 `/api/teach/continue` 从中断处恢复。

5. **图形双模式存储** — 教材图形同时存入 ChromaDB KB 图集（供教学时语义检索）和磁盘 `.figures/` 目录（供 API 直接访问）。微信作业图形仅存磁盘 `.figures/`，关联 TeachSession，不入 KB。

6. **多科隔离，互不干扰** — 每套试卷独立 TeachSession。学科检测优先从文件名推断（教材），其次从 OCR 文本关键词匹配。

---

## 三、数据存储

### 3.1 TeachSession — 每份试卷独立 JSON

```
/data/teach_sessions/ts_{uuid}.json
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | str | `ts_` 前缀 UUID |
| `learner_id` | str | 学习者标识 |
| `status` | str | `pending` → `active` → `completed` / `expired` |
| `source` | str | `wechat` / `webui` / `auto_reinforce` / `wrong_review` |
| `subject` | str | 学科 (math/physics/chemistry/chinese/...)，用于隔离 |
| `task_type` | str | `exam_paper` / `practice` / `wrong_review` |
| `ocr_text` | str | OCR 全文 |
| `source_file` | str | 原始文件路径，用于推导 `.figures/` 目录位置 |
| `total_questions` | int | 总题数 |
| `title` | str | 显示标题（OCR 自动推导或用户指定） |
| `extracted_exam` | dict | **结构化提取的试卷**（`_pre_extract_exam` 填充） |
| `progress` | dict | **教学进度**（见下） |
| `correct_count` | int | 已答对数 |
| `wrong_count` | int | 已答错数 |
| `knowledge_points` | str | 关联知识点，逗号分隔 |
| `created_at` | float | 创建时间 |
| `updated_at` | float | 最后更新时间 |
| `expires_at` | float | 过期时间（48h TTL） |

#### extracted_exam 结构

```json
{
  "questions": [
    {
      "index": 1,
      "content": "下列哪种能源最清洁？\nA.天然气 B.煤 C.氢气 D.乙醇汽油",
      "question_type": "choice",
      "options": {"A": "天然气", "B": "煤", "C": "氢气", "D": "乙醇汽油"},
      "answer_key": "C",
      "explanation": "氢气燃烧只生成水，无污染...",
      "knowledge_point": "化学/燃料/清洁能源",
      "hints": ["L1引导", "L2关键步骤", "L3完整思路"],
      "difficulty": "easy",
      "figure_ids": ["fig_abc123"]
    }
  ],
  "total": 2,
  "extracted_at": 1717000000.0
}
```

#### progress 结构

```json
{
  "current_index": 2,
  "answered_count": 1,
  "correct_count": 1,
  "answers": {
    "1": {
      "student_answer": "C",
      "is_correct": true,
      "score": 1.0,
      "dt_feedback": "太棒了！🎉",
      "dt_explanation": "氢气燃烧只生成水...",
      "completed_at": 1717000100.0
    }
  }
}
```

### 3.2 图形存储 — 双模型

#### 教材图形 (知识库)
```
/data/knowledge_bases/初中教材/raw/
  ├── 义务教育教科书·化学九年级上册.pdf
  └── 义务教育教科书·化学九年级上册.figures/
        ├── fig_abc123.png           ← 嵌入图片 (RapidOCR 提取)
        ├── ...
        └── _index.json               ← 图形元数据 (figure_id/描述/类型)

ChromaDB:
  kb_Zu4F3wD-a-s_figures              ← 图形描述向量 (教材名+OCR文字)
```

- 教材图形通过 `_store_figures_from_file` 提取 → RapidOCR 文字 → 描述富化为 `"教材：{名称}"` → 同时入 ChromaDB 和磁盘
- 教学时 `_build_teaching_persona` 通过 `provider.query(include_figures=True)` 语义检索 (distance < 1.3)
- 图形 URL: `/api/kb/figures/{figure_id}/image?kb_name=初中教材`

#### 微信作业图形 (临时)
```
/data/sources/{trace_id}_{timestamp}_{filename}
  ├── .figures/
  │     ├── fig_abc123.png           ← 裁剪图
  │     └── _index.json
  └── (原始文件)
```

- 通过 `extracted_exam[].figure_ids` 关联到题目
- 不入 ChromaDB，仅磁盘存储
- session 过期（48h）时清理

### 3.3 掌握度 — mastery JSON（不变）

```
/data/mastery/{base64(learner_id)}.json
```

现有模型不变，`wrong_answers` 包含 `session_id` 字段。

### 3.4 ChromaDB hygiene model

| 数据类型 | 存储位置 | 集合 | 说明 |
|----------|----------|------|------|
| 教材 PDF 文本 | ChromaDB | `kb_Zu4F3wD-a-s` | 知识库上传，2,816 chunks |
| 教材图形描述 | ChromaDB | `kb_Zu4F3wD-a-s_figures` | 知识库上传，1,426 条 |
| 课标知识点 | ChromaDB | `curriculum` | KP-level，298 条 |
| 用户上传文档 | ChromaDB | `kb_{hash}` | Web UI 上传的非教材文件 |
| 微信拍题 OCR | TeachSession JSON | — | **不入 ChromaDB** |
| 作业图形 | 磁盘 `.figures/` | — | **不入 ChromaDB** |
| 教学上下文 | 内存缓存 + 磁盘 | — | `_last_tutor_context` |

---

## 四、核心流程

### 4.1 微信拍题 → 教学

```
① 微信发图片
    │
② hermes_agent → POST /api/process/file (suppress_auto_teach=1)
    │   ├─ kb_name="" → 不入库
    │   └─ OCR → 文本提取 (Qwen2-VL / RapidOCR)
    │
③ 结构化提取
    │   ├─ _pre_extract_exam(ocr_text) → DeepSeek API
    │   │   └─ 题号、题目、选项、答案、解析、知识点、hints
    │   └─ 存入 _extracted_exams[learner_id] 内存缓存
    │
④ 图形提取 (fire-and-forget)
    │   └─ extract_figures(file_path) → .figures/{id}.png
    │
⑤ 创建 TeachSession → teach_sessions/{id}.json
    │   └─ 含 extracted_exam + progress
    │
⑥ 教学 (异步后台，不阻塞 OCR 返回)
    │
    ├─ _tutor_chat_core(phase="FIRST_QUESTION")
    │   ├─ _build_teaching_persona(context)
    │   │   ├─ 当前教学内容 (OCR 题目)
    │   │   ├─ KB 相关知识库参考 (ChromaDB 查询 top 3)
    │   │   ├─ KB 相关图形 (ChromaDB figures 查询)
    │   │   ├─ 课标章节 (curriculum 查询)
    │   │   ├─ 到期复习 (Ebbinghaus)
    │   │   └─ 薄弱知识点 + 近期错题
    │   ├─ _update_soul_with_context() → PATCH SOUL.md
    │   └─ Agentic Loop 或 DT WebSocket 教学
    │        ├─ Plan: 分析学生状态，选择策略
    │        ├─ Solve: 出题 (THINK→TOOL→FINISH)
    │        └─ Review: 评估 + 知识点回顾
    │
⑦ 学生作答 (微信回复文字)
    │
    └─ _tutor_chat_core(phase="EVALUATE_ANSWER")
         ├─ 判题: 用 extracted_exam.answer_key 对比学生答案
         ├─ DT 评估: 鼓励/纠正 + 讲解
         ├─ 更新 session.progress
         ├─ 更新 mastery (正确/错误 → Ebbinghaus 复习)
         └─ current_index++ 或教学结束
```

### 4.2 判题逻辑

```python
# 平台判题，不依赖 DT 的 evaluation.is_correct
_qnum = _last_question_num.get(learner_id, 1)
_exam = _extracted_exams.get(learner_id)
if _exam:
    _q = get_question_by_index(_exam, _qnum)
    correct_key = _q.answer_key
    is_correct = _match_answers(student_answer, correct_key)
else:
    # 无预提取数据 → 降级为 DT 评估结果
    is_correct = dt_result.get("evaluation", {}).get("is_correct", False)

if is_correct:
    # 掌握度 +1, 重置 hint_level
    update_mastery(kp_id, correct=True, question=q_text)
    reset_hint_level(learner_id, qnum)
else:
    # 错题保存
    update_mastery(kp_id, correct=False, question=q_text)
    advance_hint_level(learner_id, qnum)
    wrong_answers.append({...})
```

### 4.3 中断继续

```
① 学生发送 "继续" 或带 teach_session_id 的请求
    │
② _tutor_chat_core 检测: 无 context 但 message 有内容
    │   → _last_tutor_context 恢复上次教学上下文
    │   → 如果 TeachSession 不存在，尝试从磁盘恢复
    │
③ /api/teach/continue
    │   ├─ TeachSession.recover(session_id) → 从磁盘加载
    │   ├─ _extracted_exams 恢复预提取试卷数据
    │   └─ _tutor_chat_core(phase="EVALUATE_ANSWER")
    │
④ 判断 session 是否过期
    │   ├─ 未过期 → 从 progress.current_index 继续
    │   └─ 已过期 → 返回错误，提示创建新 session
```

### 4.4 知识库教材教学

```
Web UI /api/tutor/chat (mode="guide", context=教材文本)
    │
    ├─ _tutor_chat_core(context=教材章节文本)
    │   ├─ _build_teaching_persona(context)
    │   │   ├─ 检测学科 (_subject_from_filename)
    │   │   ├─ KB 相关知识库参考 (按 subject 过滤)
    │   │   ├─ KB 相关图形 (同 subject 的教材插图)
    │   │   └─ 课标章节 (curriculum 查询)
    │   └─ DT 教学: 苏格拉底引导 + 教材内容 + 插图引用
    │
    └─ 图形注入: 回复末尾追加匹配的教材图形 ![desc](url)
```

### 4.5 图形 API

```python
@app.get("/api/kb/figures/{figure_id}/image")
def get_figure_image(figure_id: str, kb_name: str = ""):
    """从知识库 .figures/ 目录查找教材图形。
    
    搜索顺序：
    1. /data/knowledge_bases/{kb_name}/raw/*.figures/{figure_id}.png
    2. /data/sources/**/*.figures/{figure_id}.png (fallback)
    """
    for root in ("/data/knowledge_bases", "/data/sources"):
        matches = glob.glob(f"{root}/**/*.figures/{figure_id}.png", recursive=True)
        if matches:
            return Response(Path(matches[0]).read_bytes(), media_type="image/png")
    return Response(status_code=404)
```

---

## 五、DT 教学能力利用

| 能力 | 实现方式 | 状态 |
|------|----------|------|
| **Hint Ladder (0-3级)** | 答错后 `advance_hint_level`，SOUL.md 注入 `{hint_level}` | ✅ |
| **苏格拉底引导** | FIRST_QUESTION 时 Agentic Loop Plan→Solve 阶段出引导问题 | ✅ |
| **元认知引导 (A/B/C)** | `teach_loop.py` Plan 阶段引导学生识别知识点 | ✅ |
| **答案评判** | DT 评估作为参考展示，platform 用 `answer_key` 最终判题 | ✅ 平台覆盖 |
| **错因归因** | DT 在讲解中分析错因（概念/计算/审题） | ✅ |
| **讲解+解析** | DT 用预提取的 `explanation` 做讲解 | ✅ |
| **变式巩固** | Level 2+ 时 DT 自动出同类变式题 | ✅ |
| **Ebbinghaus 复习** | 到期复习注入 `_build_teaching_persona` → SOUL.md | ✅ |
| **题号管理** | `teach_loop.py` / `_tutor_chat_core` 在 platform 侧管理 | ❌ DT 不管 |
| **下一题选择** | platform 按 `extracted_exam` 索引决定 | ❌ DT 不管 |
| **KB 教材引用** | SOUL.md 注入 KB 参考文本 + 图形 Markdown | ✅ |
| **知识图谱** | curriculum ChromaDB 集合 + `kp_id` 关联 | ✅ |

---

## 六、Web 页面设计（规划参考）

### 6.1 学习仪表盘 (`/space`)

```
┌──────────────────────────────────────────────────────┐
│  📚 今天的学习                   2026-06-07 周日      │
│                                                      │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐             │
│  │ 答题  │  │ 正确率│  │ 进行中│  │ 待复习 │             │
│  │  12   │  │  75%  │  │  2   │  │  3   │             │
│  └──────┘  └──────┘  └──────┘  └──────┘             │
│                                                      │
│  📊 知识点掌握度                                      │
│  数学  ████████░░  80%                                │
│  物理  ██████░░░░  60%  ← 薄弱                        │
│  化学  ███████░░░  70%                                │
│                                                      │
│  📋 进行中的任务                                       │
│  ┌──────────────────────────────────────────────┐    │
│  │ 2024数学期中卷 · 第3/5题    [继续] [查看详情]  │    │
│  │ 物理浮力强化练习 · 第0/5题  [继续] [查看详情]  │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  ⏰ 到期复习 (Ebbinghaus)                             │
│  ┌──────────────────────────────────────────────┐    │
│  │ 幂的运算 · 掌握度40% · 逾期1天  [开始复习]    │    │
│  │ 全等三角形 · 掌握度55% · 今天到期  [开始复习]  │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  🎯 薄弱知识点 (掌握度<60%)                           │
│  ┌──────────────────────────────────────────────┐    │
│  │ 物理/浮力/阿基米德原理    40%  [生成练习]     │    │
│  │ 数学/二次函数/顶点坐标    45%  [生成练习]     │    │
│  │ 数学/三角形/全等三角形    55%  [生成练习]     │    │
│  └──────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘
```

### 6.2 逐题教学 (`/teach/{session_id}`)

```
┌──────────────────────────────────────────────────────┐
│  ← 返回仪表盘   数学 · 2024期中卷    第 3/5 题       │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ [图] 题目内容...                              │    │
│  │ 选项 A.  B.  C.  D.                          │    │
│  │ (如有教材图形: ![教材插图](figure_url))         │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  💡 引导问题...                                       │ ← DT
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ 输入答案...                              提交  │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  答对 ✓  🎉  [DT 讲解 + KB 知识点扩展]              │
│  答错 ✗  [DT hint → 变式巩固 → 完整解析]              │
│                                                      │
│  [◀ 上一题]  [下一题 ▶]  [📕 错题本]               │
└──────────────────────────────────────────────────────┘
```

### 6.3 错题本 (`/wrong-answers`)

```
┌──────────────────────────────────────────────────────┐
│  错题本                                  共 12 题    │
│  学科: [全部 ▼]  知识点: [全部 ▼]                    │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ ✗ 第2题 · 数学/三角形/全等三角形              │    │
│  │ 答: B  正确: C  2026-06-07                   │    │
│  │ [重新练习] [查看原卷]                          │    │
│  └──────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────┐    │
│  │ ✗ 第5题 · 物理/浮力                          │    │
│  │ ... [重新练习]                                 │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  [批量练习选中错题]                                   │
└──────────────────────────────────────────────────────┘
```

**重新练习** → 创建新 session（`source=wrong_review`）：只包含选中的错题，走同样的逐题教学流程。

---

## 七、各角色职责

| 角色 | 职责 | 不做 |
|------|------|------|
| **DeepSeek (提取)** | OCR 后一次性提取题目+答案+解析+hints | 不参与后续教学 |
| **platform** | 题号管理、判题、session 持久化、掌握度更新、导航控制、KB 入库防护、图形管道、学科检测、Agentic Loop 教学管程 | — |
| **DT** | 苏格拉底引导、hint ladder、讲解、鼓励/纠正、变式出题、KB 教材引用 | 不出新题号、不判题、不控制进度 |
| **ChromaDB** | 教材文本+图形向量检索（KB 集合）、课标知识点索引 | 不收微信作业/试卷数据 |
| **TeachSession JSON** | 存每次教学会话全部数据（试题、进度、答案） | 不与 ChromaDB 混淆 |
| **磁盘 `.figures/`** | 教材图形（长期）、作业图形（48h TTL） | — |
