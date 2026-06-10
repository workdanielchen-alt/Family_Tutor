# K9 深度学习系统架构文档

> 版本: v1.0
> 日期: 2026-06-07
> 目标: 微信拍题 + Web 深度学习，系统性提高 K9 孩子学习成绩

---

## 一、整体架构

```
                         ┌──────────────────┐
                         │   用户入口         │
                         │ 微信拍照 / Web UI  │
                         └────────┬─────────┘
                                  │
                          ┌───────▼────────┐
                          │  OCR 预处理      │
                          │ (Qwen2-VL)      │
                          └───────┬────────┘
                                  │ OCR 文本
                          ┌───────▼────────┐
                          │  一次性提取       │
                          │  DeepSeek API    │
                          │  ─ 结构化题目    │
                          │  ─ 答案+解析     │
                          │  ─ 知识点标记    │
                          └───────┬────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
              ┌─────▼────┐ ┌─────▼────┐ ┌─────▼────┐
              │ 图形提取   │ │ Teach    │ │ 原图归档  │
              │ -> .fig/  │ │ Session  │ │ -> sources│
              └──────────┘ │ JSON     │ └──────────┘
                           └─────┬────┘
                                 │
                    ┌────────────┴────────────┐
                    │      逐题教学流程         │
                    │  (平台控流程 + DT 教学)    │
                    └────────────┬────────────┘
                                 │ 每道题结果
                    ┌────────────┴────────────┐
                    │   掌握度 / 错题本 JSON    │
                    │   (mastery/{id}.json)    │
                    └─────────────────────────┘
```

---

## 二、设计原则

1. **微信拍照为首要入口** — 日常作业辅导通过微信完成，Web UI 做深度学习
2. **DT 做教学不做管理** — 题号、判题、导航由平台控制，DT 专注引导式教学
3. **文件即数据库** — 每份试卷独立 JSON 文件，不依赖 ChromaDB 存储临时数据
4. **图形随 session 走** — 提取到磁盘，关联 session，不写入向量库
5. **互不干扰** — 每套试卷独立 session，不同学科隔离，微信拍题不进教材知识库
6. **中断可继续** — session 持久化到磁盘，48h TTL，随时恢复教学进度

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
| `subject` | str | 学科 (math/physics/chemistry/...)，用于隔离 |
| `ocr_text` | str | OCR 全文 |
| `source_file` | str | 原始文件路径，用于推导 `.figures/` 目录位置 |
| `total_questions` | int | 总题数 |
| `title` | str | 显示标题 |
| `extracted_exam` | dict | **结构化提取的试卷**（见下）|
| `progress` | dict | **教学进度**（见下）|
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

### 3.2 图形存储 — 磁盘 + session 关联

```
/data/sources/{trace_id}_{timestamp}_{filename}
  │
  ├── .figures/
  │     ├── fig_abc123.png       ← 裁剪图
  │     ├── fig_def456.png
  │     └── _index.json          ← 图ID → 题号映射
  │
  └── (原始文件)
```

- 图形从 ChromaDB 中**移出**，仅存磁盘
- 通过 `extracted_exam[].figure_ids` 关联到题目
- 教学时 API 从 `source_file` 同级的 `.figures/` 读取
- session 过期（48h）时清理对应的 `.figures/` 目录

### 3.3 掌握度 — 现有 mastery JSON（不变）

```
/data/mastery/{base64(learner_id)}.json
```

现有模型不变，唯一变化：`wrong_answers` 增加 `session_id` 字段。

### 3.4 ChromaDB — 只保留教材

| 数据 | 去向 | 说明 |
|------|------|------|
| 教材 PDF（知识库上传） | ChromaDB `kb_xxx` | ✅ 保留 |
| 微信拍题 / 作业 | TeachSession JSON | ✅ 移出 ChromaDB |
| 自动强化试卷 | TeachSession JSON | ✅ 移出 ChromaDB |
| 图形索引 | 磁盘 `.figures/` | ✅ 移出 ChromaDB |

---

## 四、核心流程

### 4.1 微信拍题 → 教学

```
① 微信发图片
    │
② OCR → 文本提取
    │
③ extract_figures() → .figures/{id}.png
    │
④ DeepSeek API: OCR 文本 → 结构化提取
    │  ├─ 题号、题目、选项、答案、解析、知识点
    │  └─ 图形关联: "如图X" → 匹配附近 figure_id
    │
⑤ 创建 TeachSession → teach_sessions/{id}.json
    │
⑥ 逐题教学循环
    ├─ [平台] 取 session.extracted_exam[current_index]
    ├─ [平台] 构建 DT prompt（当前题 + 图URL + hint_level）
    ├─ [DT]   引导问题输出
    ├─ [学生] 作答
    ├─ [平台] 判题（用 answer_key，不依赖 DT 评估）
    ├─ [平台] 更新 session.progress
    ├─ [平台] 更新 mastery
    └─ current_index++ 或结束
```

### 4.2 判题逻辑

```python
# 平台判题，不依赖 DT 的 evaluation.is_correct
correct_key = session.extracted_exam.questions[current_index - 1].answer_key
is_correct = match_answers(student_answer, correct_key)

if is_correct:
    mastery.correct_count++
    reset_hint_level(learner_id, current_index)
else:
    mastery.wrong_count++
    advance_hint_level(learner_id, current_index)
    wrong_answers.append({
        "question": q.content,
        "answer_key": correct_key,
        "student_answer": student_answer,
        "kp_id": q.knowledge_point,
        "session_id": session.session_id,
    })

# DT 的教学评语保留，用于前端展示
result = {
    "is_correct": is_correct,          # 平台判题
    "score": score,                     # 平台评分
    "correct_answer": correct_key,      # 平台持有
    "feedback": dt_feedback,            # DT 鼓励/纠正
    "explanation": dt_explanation,      # DT 讲解
}
```

### 4.3 中断继续

```python
session = teach_store.get(session_id)
if session.is_expired:
    return {"error": "session_expired"}

progress = session.progress
current_index = progress.current_index

if current_index < len(session.extracted_exam.questions):
    question = session.extracted_exam.questions[current_index]
    # 正常教学流程...
```

### 4.4 图形获取 API

```python
@app.get("/api/kb/figures/{figure_id}/image")
def get_figure_image(figure_id: str, source_file: str = ""):
    """从 source_file 同级的 .figures/ 目录查找。"""
    if source_file:
        fig_dir = Path(source_file).parent / f"{Path(source_file).stem}.figures"
        for ext in (".png", ".jpg"):
            path = fig_dir / f"{figure_id}{ext}"
            if path.exists():
                return Response(path.read_bytes(), media_type=f"image/{ext[1:]}")
    
    # fallback: 全局搜索
    for root in ("/data/sources", "/data/knowledge_bases"):
        matches = glob.glob(f"{root}/**/*.figures/{figure_id}.png", recursive=True)
        if matches:
            return Response(Path(matches[0]).read_bytes(), media_type="image/png")
    
    return Response(status_code=404)
```

---

## 五、DT 教学能力利用

| 能力 | 使用方式 | 保留/增强 |
|------|----------|-----------|
| **Hint Ladder (0-3级)** | 答错后递增 hint_level，DT 按级给出提示 | ✅ 保留 |
| **苏格拉底引导** | FIRST_QUESTION 时 DT 出引导问题 | ✅ 保留 |
| **元认知引导 (A/B/C)** | 引导学生识别知识点、做解题计划 | ✅ 保留 |
| **答案评判** | DT 评估作为参考，平台用 answer_key 最终判题 | ✅ 平台覆盖 |
| **错因归因** | DT 在讲解中分析错因（概念/计算/审题） | ✅ 保留 |
| **讲解+解析** | DT 用预提取的 explanation 做讲解 | ✅ 保留 |
| **变式巩固** | Level 2+ 时 DT 自动出同类变式题 | ✅ 保留 |
| **Ebbinghaus 复习** | 到期复习注入教学流程 | ✅ 保留 |
| **题号管理** | DT 不再管理题号 | ❌ 平台接管 |
| **下一题选择** | DT 不再决定出哪一题 | ❌ 平台接管 |

---

## 六、Web 页面设计

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
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  💡 引导问题...                                       │ ← DT
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │ 输入答案...                              提交  │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  答对 ✓  🎉  [DT 讲解]                              │
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

**重新练习** → 创建新 session（`source=wrong_review`）：
- 只包含选中的错题
- 走同样的逐题教学流程
- DT 重新引导 + 平台判题
- 答对 → 从错题本移除

---

## 七、各角色职责

| 角色 | 职责 | 不做 |
|------|------|------|
| **DeepSeek (提取)** | OCR 后一次性提取题目+答案+解析 | 不参与后续教学 |
| **平台** | 题号管理、判题、session 持久化、掌握度更新、导航控制 | — |
| **DT** | 苏格拉底引导、hint ladder、讲解、鼓励/纠正、变式出题 | 不出新题号、不判题、不控制进度 |
| **ChromaDB** | 只存教材 PDF（知识库上传） | 不收作业/试卷数据 |
| **TeachSession JSON** | 存每次教学会话全部数据 | 不与 ChromaDB 混淆 |

---

## 八、文件改动清单

### 修改

| 文件 | 改动 |
|------|------|
| `tutor_platform/teach_session.py` | `TeachSession` 加 `extracted_exam` 字段（JSON 序列化） |
| `docker/platform/provider_api.py` | ① `_handle_inbound_file`：OCR 后不入库 ChromaDB（删 Step 3） |
| | ② `_tutor_chat_core`：从 session 读 extracted_exam |
| | ③ 判题用 session.answer_key，不依赖 DT |
| | ④ 图形 API 加 `source_file` 参数 |
| | ⑤ session 过期清理 |
| `docker/platform/periodic_tasks.py` | 加 `cleanup_expired_sessions()` |
| `web/components/quiz/GuidedQuizFlow.tsx` | 加上一题导航 + 变式巩固 inline |
| `web/app/(app)/space/wrong-answers/page.tsx` | 错题本 → 点击重新练习 |

### 不改

| 文件 | 理由 |
|------|------|
| `vendor/deeptutor/deeptutor/` | vendor 代码，不动 |
| `domains/tutoring/mastery.py` | 掌握度模型不变 |
| `tutor_platform/unified_provider.py` | ChromaDB 操作不变（教材用） |
| ChromaDB 现有 `kb_xxx` | 教材数据不受影响 |

---

## 九、实施优先级

| 阶段 | 内容 | 工期 |
|------|------|------|
| **P0.1** | `TeachSession.extracted_exam` 字段 + JSON 序列化 | 0.5d |
| **P0.2** | `_handle_inbound_file` 去除 ChromaDB 入库 + 改存 session | 1d |
| **P0.3** | `_tutor_chat_core` 从 session 验证 DT 输出、用 answer_key 判题 | 1d |
| **P0.4** | 图形 API 支持 `source_file` 参数 | 0.5d |
| **P1** | 中断继续 + session 过期清理 | 0.5d |
| **P2** | Web 错题本重做、上一题导航 | 1d |
| **P3** | 学习仪表盘（按第六章设计优化） | 1d |
