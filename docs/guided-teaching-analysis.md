# DT BOT 引导式教学体系 — 完整分析与优化方案

> 基于 provider_api.py (7054行)、weixin.py (2619行)、guided-teaching patch (822行)、hermes-wechat patch (554行)、mastery.py、ARCHITECTURE.md、PRD.md 的完整代码审查。

---

## 目录

1. [系统运作全景](#1-系统运作全景)
2. [三态会话引擎](#2-三态会话引擎)
3. [LLM 调用路径](#3-llm-调用路径)
4. [教学人格构建](#4-教学人格构建)
5. [关键观察与问题诊断](#5-关键观察与问题诊断)
6. [优化方案 P0 — 立即提升孩子体验](#6-p0-优化方案)
7. [优化方案 P1 — 教学流畅性](#7-p1-优化方案)
8. [优化方案 P2 — 稳定性增强](#8-p2-优化方案)
9. [实施路线图](#9-实施路线图)
10. [当前系统核心机制对照表](#10-当前系统核心机制对照表)

---

## 1. 系统运作全景

### 1.1 数据流

```
┌──────────────────────────────────────────────────────────────────────┐
│                         孩子微信                                     │
│              拍照发试卷 / 文字回复答案 / 说"累了"                      │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ iLink 长轮询
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  hermes_agent 子网关 (weixin.py)                                    │
│                                                                      │
│  _route_child_message — 三态会话引擎                                  │
│    ├─ 新文件 → 创建 session(active) → _run_teaching_flow            │
│    ├─ 教学态+文字 → _run_teaching_flow(follow-up)                   │
│    ├─ 暂停信号 → state=paused                                       │
│    ├─ 恢复信号 → state=active, 恢复上下文                            │
│    ├─ 暂停态+其他 → handle_message(HA 闲聊)                          │
│    └─ 无会话 → handle_message(HA agent)                             │
│                                                                      │
│  _running_teachings: set[str] — per-learner 并发守卫                │
│  _teaching_sessions: dict → 磁盘 JSON 持久化                         │
│  2h 无活动自动回收                                                   │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ POST /api/process/file
                             │ POST /api/tutor/chat
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  platform (provider_api.py) — 编排层                                 │
│                                                                      │
│  /api/process/file — 文件处理流水线                                  │
│    ├─ SHA256 去重(30min TTL)                                        │
│    ├─ OCR warm-check (持久化标记)                                    │
│    ├─ OpenCV 预处理(去偏斜/去噪/CLAHE)                               │
│    ├─ rkllama NPU OCR (Semaphore=2 防OOM)                           │
│    ├─ vision 图描述 (缓存1h)                                         │
│    ├─ 教育内容检测 (关键词+数学符号+试卷格式)                         │
│    └─ 异步写入知识库 ChromaDB                                        │
│                                                                      │
│  /api/tutor/chat → _tutor_chat_core()                               │
│    Step 1: 上下文恢复                                                │
│    Step 2: _build_teaching_persona() 构建教学人格                    │
│    Step 3: 更新 SOUL.md (HTTP PATCH, 缓存去重)                      │
│    Step 4: 构建 LLM payload [PHASE:FIRST_QUESTION/EVALUATE_ANSWER]  │
│    Step 5: 三路径 LLM 调用 (Direct DeepSeek → rkllama → DT WS)     │
│    Step 6: 后处理 (多题截断/分析表剥离/答案提取/完成检测)            │
│    Step 7: 掌握度更新 update_mastery()                              │
│    Step 8: 触发后续动作 (同类题巩固/强化试卷生成)                    │
│                                                                      │
│  后台 60s tick: _periodic_task_loop()                                │
│    ├─ sync_quiz_to_mastery (300s)                                   │
│    ├─ report_scheduler (日报20:00 / 周报周一 / 月报1日)             │
│    └─ 强化试卷推送 (20:00后, 薄弱点≥3)                              │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ send() 微信消息
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  child 微信收到回复                                                   │
│                                                                      │
│  [PHASE:FIRST_QUESTION]                                              │
│  第1题：题目内容                                                     │
│  选项A... B...                                                       │
│  [ANSWER_KEY:X]  [KP_ID:学科/章/节]                                  │
│  想想看，全面调查需要逐一统计每个个体...                               │
│                                                                      │
│  [PHASE:EVALUATE_ANSWER]                                             │
│  第1题 ✅                                                            │
│  【知识点：XXX】                                                     │
│  正确答案是X。简要讲解...                                             │
│  ════════════════════════════════════════════                        │
│  ✅ 正确答案：X                                                      │
│  ════════════════════════════════════════════                        │
│  第2题：下一题内容                                                   │
│  选项... [ANSWER_KEY:Y]  [KP_ID:...]                                 │
│  你的思路是？                                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 组件交互时序

```
孩子微信          HA子网关           platform(编排层)     DT引擎          LLM
   │                 │                    │               │              │
   │──发图片/试卷────→│                    │               │              │
   │                 │──📎收到，正在处理──→│               │              │
   │                 │                    │               │              │
   │                 │──POST /api/process/file────────────→│              │
   │                 │                    │──OCR───────────────→rkllama  │
   │                 │                    │←──OCR结果──────────────────│
   │                 │←──OCR结果──────────│               │              │
   │                 │                    │               │              │
   │                 │──📄第1页看清楚了──→│               │              │
   │                 │                    │               │              │
   │                 │──POST /api/tutor/chat──────────────→│              │
   │                 │                    │──构建SOUL.md──→│              │
   │                 │                    │               │──LLM调用────→│
   │                 │                    │               │←──回复──────│
   │                 │←──教学回复──────────│               │              │
   │                 │                    │               │              │
   │←──第1题+引导────│                    │               │              │
   │                 │                    │               │              │
   │──回复答案───────→│                    │               │              │
   │                 │──POST /api/tutor/chat──────────────→│              │
   │                 │                    │               │──LLM调用────→│
   │                 │                    │               │←──回复──────│
   │                 │←──评判+下一题──────│               │              │
   │←──评判+第2题────│                    │               │              │
```

---

## 2. 三态会话引擎

### 2.1 状态机

```
                    ┌──────────────┐
                    │   无会话      │
                    │   (None)     │◄────── 2h 无活动
                    └──────┬───────┘
                           │
             新图片/新文件 ─→ 创建 session(state=active)
             磁盘恢复会话 ─→ 同上
                           │
                    ┌──────▼───────┐
                    │  教学态       │◄──── 恢复信号
                    │  (active)     │
                    └──────┬───────┘
                           │
             暂停信号 ──→ state=paused
                           │
                    ┌──────▼───────┐
                    │  暂停态       │──── 恢复信号 ──→ 教学态
                    │  (paused)     │──── 其他文字 ──→ HA 闲聊
                    └──────────────┘
```

### 2.2 会话数据模型

```python
teaching_session = {
    "state": "active",          # active / paused
    "started_at": 1234567890,   # 开始时间戳
    "last_active": 1234567890,  # 上次活动时间
    "question_num": 3,          # 当前做到第几题
    "total_questions": 12,      # 总题数（OCR估算）
    "trace_id": "abc123",       # 追踪ID
}
```

### 2.3 信号集

| 类别 | 当前信号词 | 行为 |
|------|-----------|------|
| 暂停 | `累了`, `休息一下`, `聊会天`, `想聊天`, `不学了`, `先不学了`, `休息`, `歇会`, `先休息`, `不想学了`, `聊聊天`, `说会话` | state → paused |
| 恢复 | `继续`, `接着`, `回来`, `好了`, `继续做题`, `接着学`, `开始学习`, `回来做题`, `继续学习`, `开始做题` | state → active |
| 教学内 | `问个问题`, `help`, `结束`, `讲一下`, `不会`, `不懂` | 留在教学态，LLM自行判断 |

---

## 3. LLM 调用路径

### 3.1 优先级与路径

```
Path A: Direct DeepSeek API (3-5s)
  ├─ 条件: 无 (始终可用)
  ├─ 绕过: DT AgentLoop、SOUL.md、WS 连接
  ├─ 优点: 最快路径
  └─ 弱点: 无重试/熔断

Path B: Local NPU rkllama (10-30s)
  ├─ 条件: _llm_lock.acquire(timeout=5s) 成功
  ├─ 绕过: DT AgentLoop、WS
  ├─ 优点: 免费、本地处理
  └─ 弱点: r1-distill-1.5B 能力有限 (<20字自动降级)

Path C: DT WebSocket → DeepSeek 云端 (30-80s)
  ├─ 条件: Path A/B 均失败
  ├─ 路径: WS → DT AgentLoop → DeepSeek → WS
  ├─ 优点: 能力最完整
  └─ 弱点: 最慢，profile switch 额外开销
```

### 3.2 LLM 资源锁

```
_llm_lock = _TTLock(ttl=120s)

DT 教学获取锁: timeout=5s
  ├─ 成功 → DT 切到 rkllama 配置 → 本地 NPU 教学
  └─ 超时 → DT 切到 deepseek 配置 → 云端 API 教学

HA OCR 获取锁: timeout=60s (300s 原始, 实际 60s)
  └─ 等待 (DT 教学通常 30-60s 完成)

Stale 检测: 持有超过 TTL → force_release → 防止死锁
```

---

## 4. 教学人格构建

### 4.1 `_build_teaching_persona()` 注入内容

```
_TEACHER_SOUL (基底)
  ├─ 苏格拉底引导规则
  ├─ PHASE:FIRST_QUESTION / EVALUATE_ANSWER 模式指令
  ├─ 引导问题规范（好/坏示例）
  └─ 闲聊与教学外处理规则

+ 当前试卷原文 (≤8000字符)
+ 课程章节 (ChromaDB curriculum, top-1)
+ 知识库参考 (ChromaDB tutoring, top-3, 去重)
+ 到期复习 (Ebbinghaus: 1/3/7/14/30天间隔)
+ 薄弱知识点 (掌握度<0.6, top-5)
+ 近期错题 (最近5条)
+ 自动生成试卷 (如存在)

→ HTTP PATCH DT /api/v1/tutorbot/teacher (SOUL.md)
  └─ _last_persona[learner_id] 缓存比对 → 无变更跳过HTTP
```

### 4.2 SOUL.md 关键指令摘要

**FIRST_QUESTION 模式**：一次只出 1 题、题号必须阿拉伯数字、禁止答案提示、引导问题不能直接问答案。

**EVALUATE_ANSWER 模式**：评判+讲解+自动出下一题（两步合一）、末尾必须带 `[ANSWER_KEY:X]` 和 `[KP_ID:...]` 标记。

**闲聊处理**：问问题/求讲解留在教学态展开；累了/想聊天才切暂停。

---

## 5. 关键观察与问题诊断

### 5.1 体验问题矩阵

| 维度 | 当前表现 | 严重度 | 影响面 |
|------|----------|--------|--------|
| **响应感知** | 发图后"📎收到"，然后无声等待 10-30s | 🔴 高 | 孩子以为没发出去，可能重复发送 |
| **等待焦虑** | OCR + LLM 串行执行，无中间进度 | 🔴 高 | 注意力容易分散 |
| **语气僵化** | 全年龄段统一 prompt，无适配 | 🔴 高 | 低龄孩子觉得太正式，大孩子觉得幼稚 |
| **鼓励不足** | 只有完成时有总结，"答对了"无额外激励 | 🟡 中 | 缺少持续动力 |
| **挫败感** | 连续答错只出同类题，无降级鼓励 | 🟡 中 | 可能产生"我不行"的习得性无助 |
| **进度不明** | 不显示整体进度（第几题/共几题） | 🟡 中 | 孩子不知道还要做多久 |
| **拍照要求** | OCR 模糊时直接让"再发一次" | 🟡 中 | 低年级孩子不知道怎样才算清晰 |
| **暂停不灵敏** | 信号词硬编码，"妈妈叫我吃饭"不会被识别 | 🟡 中 | 孩子想停时停不了 |
| **回复过长** | 微信 2048 限制，长回复可能被截断 | 🟢 低 | 偶发，不频繁 |
| **题数不准** | 正则估算 3000 字符，失败时回退 25 道 | 🟢 低 | 偶尔提前结束或延长 |
| **无响应** | 孩子发消息后 LLM 超时→"教学未响应" | 🟢 低 | 偶发，但体验差 |
| **学习状态** | 未感知今日状态（已做多少题/正确率） | 🟢 低 | 缺失针对性调整 |

### 5.2 稳定性风险矩阵

| 风险点 | 当前防护 | 评估 | 建议 |
|--------|----------|------|------|
| SOUL.md 并发写入 | 全局锁 + 版本号 | ✅ 充分 | 保留 |
| 孩子连发消息 | `_running_teachings` 去重 | ✅ 充分 | 保留 |
| 容器重启丢上下文 | JSON 磁盘持久化 + 恢复 | ✅ 充分 | 保留 |
| DT WS 断连 | 自动重连 + keepalive 30s | ✅ 充分 | 保留 |
| iLink 5min 窗口 | 提前释放并发锁不等发送 | ✅ 充分 | 保留 |
| 本地 NPU 锁泄漏 | TTL 120s force_release | ✅ 充分 | 保留 |
| 文件去重 | SHA256 + LRU 30min TTL | ✅ 充分 | 保留 |
| ✅ 现有防护充分 | | | |
| Direct DeepSeek 挂 | ❌ 无重试 | 缺失 | 增加 1 次重试 |
| 单 learner 卡题 | ❌ 无超时提醒 | 缺失 | 新增 5min 无回复提醒 |
| OCR 模糊无降级 | ❌ 直接让重发 | 缺失 | 分层次引导重拍 |

---

## 6. P0 优化方案

### 6.1 渐进式反馈（消除等待焦虑）

**问题**：发图到看到题目的 10-30s 内，孩子只看到一条"📎收到"，后面完全黑盒。

**方案**：`_run_teaching_flow()` 中改为多阶段 IM 反馈

```
时间线：
0.0s  →  "📎 收到！正在读题..."
2.0s  →  第1页OCR完成 → "📄 第1页看清楚了"
5.0s  →  第2页OCR完成 → "📄 第2页也看清了，正在出题..."
8.0s  →  LLM 返回 → 直接展示第1题+引导

效果对比：
  当前：收到 → (静默15s) → 第一题
  优化：收到 → (2s)第1页 → (5s)第2页 → (8s)第一题
  孩子感知：系统一直在工作，不是"卡死了"
```

**改动文件**：`vendor/hermes-agent/gateway/platforms/weixin.py` — `_run_teaching_flow()`

---

### 6.2 年龄段自适应教学语气

**问题**：`_TEACHER_SOUL` 的语调统一，6岁和14岁孩子需求完全不同。

**方案**：在 `_build_teaching_persona()` 注入年龄段指令

```
年级信息来源：
  - 绑定孩子时存储年级字段 (learner metadata JSON)
  - 或由 LLM 通过题目内容推断

小学低年级(1-3):
  - 语气亲切活泼，称呼"小朋友"
  - 多使"我们一起看看""试试看"
  - 答对 → "太棒了！🎉"
  - 答错 → "没关系，这道题有点绕，换个角度想"
  - 用生活化例子解释概念
  - 单次最多5道题
  - 引导问题要非常具体、指向明确

小学高年级(4-6):
  - 朋友式语气
  - 答对 → "完全正确！" + 知识点总结
  - 答错 → "这个地方容易被绕进去，我们来看..."
  - 可接受少量抽象概念
  - 引导问题留适量思考空间

初中(7-9):
  - 专业尊重的语气
  - 答对 → 扩展性提问（"还能用其他方法解吗？"）
  - 答错 → 归因分析（概念不清/计算失误/审题问题）
  - 关注方法论和思维过程
  - 引导问题注重逻辑推理
```

**改动文件**：`docker/platform/provider_api.py` — `_build_teaching_persona()` + learner 数据格式

---

### 6.3 高频正向激励系统

**问题**：孩子答对后只有"这道题的正确答案是X"，缺少持续的情感激励。

**方案**：在 `_TEACHER_SOUL` 和 `_patch_soul()` 嵌入激励规则

```
## 正向反馈规则
- 每答对一题 → "很好！" 级别鼓励
- 连续答对3题 → "已经连续答对3道了！状态很好！"
- 连续答对5题 → "🔥 连续答对5道，今天状态火热！"
- 首次答对薄弱知识点题 → "这个知识点掌握了，进步很大！"
- 今日首答正确 → "今天第一道题就对了，好开局！"
- 答错后纠正 → "对！刚才错的地方现在理解了，这就是进步"
- 避免: "这题很简单"/"怎么又错了" 等负面暗示
```

**改动文件**：`docker/platform/provider_api.py` — `_TEACHER_SOUL` 字符串常量

---

### 6.4 进度可见性

**问题**：孩子不知道还有几题，容易产生"还有多少"的焦虑。

**方案**：每次回复开头嵌入文本进度条

```
[████████░░░░] 第5题/共8题  |  ✅答对3道  继续加油！
     ↑ 已做5题            ↑ 总8题

完成时：
🎉 全部完成！共8道题，答对3道答错2道
【薄弱知识点】幂的运算, 分式方程
```

**实现**：`_tutor_chat_core()` 后处理阶段，从 `_last_question_num` 和 session 的 `total_questions` 计算进度。

**改动文件**：`docker/platform/provider_api.py` — `_tutor_chat_core()` 后处理

---

## 7. P1 优化方案

### 7.1 暂停/恢复信号词扩展

**问题**：信号词硬编码，孩子会说"妈妈叫我吃饭""先放这儿"。

**方案 A（纯代码扩展，推荐先实施）**：

```python
_PAUSE_SIGNALS_EXT = _PAUSE_SIGNALS | {
    "等一下", "妈妈叫我", "吃饭了", "要走了",
    "下次再做", "先不做了", "先放这", "等会儿",
    "先去", "有事", "待会", "先不学了",
    "不想做了", "太累了", "困了", "歇会",
}
_RESUME_SIGNALS_EXT = _RESUME_SIGNALS | {
    "回来了", "来了", "做完了", "我好了",
    "我又来了", "继续吧", "开始吧", "来吧",
}
# 前缀匹配
_ANY_PAUSE = any(text.strip().startswith(kw) for kw in
    ("累了", "休息", "聊", "先", "等一下", "等会", "下次", "吃饭"))
```

**方案 B（+LLM 轻量意图判断，备选）**：模糊区域通过 Path A 快速判断意图。

**改动文件**：`vendor/hermes-agent/gateway/platforms/weixin.py` — `_route_child_message()`

---

### 7.2 错误容忍与降级策略

**问题**：连续答错仍出同类题，孩子易产生挫败感。

**方案**：`_TEACHER_SOUL` 尾部追加降级指令

```
## 降级教学规则
- 学生第1次答错 → 正常讲解，鼓励再试
- 学生第2次答错 → 换一个更简单的角度提问
- 学生第3次答错 → 先讲知识点，再出基础变式题
- 连续3次↔同一知识点 → 自动建议休息
- 学生说"好难""不会" → 降低难度，给分步提示
- 避免在同一题上纠缠超过3轮
```

**改动文件**：`docker/platform/provider_api.py` — `_TEACHER_SOUL` 尾部追加

---

### 7.3 OCR 低质量友好引导

**问题**：OCR 失败时直接让"重发"，对低龄孩子不够友好。

**方案**：`_handle_inbound_file()` 分层次反馈

```
1. OCR 文本 ≥ 80 字 → 正常教学（虽然少但够用）
2. OCR 文本 20-79 字 → "我看到了一些字但不完整。
   方便再拍一张更清晰的照片吗？"
3. OCR 文本 < 20 字 → "这张照片我看不太清。
   试试：①把手机拿平 ②光线好一点 ③不要反光
   或者直接把题目打字发给我"
```

**改动文件**：`docker/platform/provider_api.py` — `_handle_inbound_file()` OCR 失败分支

---

## 8. P2 优化方案

### 8.1 Direct DeepSeek API 重试

**问题**：最快路径（Path A）无重试，一次失败直接降级。

**方案**：`_direct_deepseek_chat()` 增加 1 次重试

```python
for attempt in range(2):
    try:
        resp = await client.post(...)
        if resp.status_code == 200:
            return content
        elif attempt == 0:
            await asyncio.sleep(1)
            continue
    except (httpx.TimeoutException, httpx.NetworkError):
        if attempt == 0:
            await asyncio.sleep(1)
            continue
    return None
```

**改动文件**：`docker/platform/provider_api.py` — `_direct_deepseek_chat()`

---

### 8.2 卡题自动提醒

**问题**：孩子在一道题上卡很久无响应，没有任何干预。

**方案**：`_route_child_message()` 教学态入口检查时间戳

```python
# 在孩子下一条消息到达时检查
_last_active = _session.get("last_active", 0)
_idle = time.time() - _last_active
if 300 < _idle < 600:
    # 5-10分钟无回复 → 提醒
    await self.send("这道题需要提示吗？要不要先看讲解？", chat_id)
elif _idle >= 600:
    # 10分钟+ → 自动暂停
    _session["state"] = "paused"
    await self.send("这道题我们先放一放，下次再来做", chat_id)
```

**改动文件**：`vendor/hermes-agent/gateway/platforms/weixin.py` — `_route_child_message()`

---

### 8.3 多策略题数估算

**问题**：总题数不准确导致试卷提前结束或迟迟不结束。

**方案**：`_tutor_chat_core()` 完成检测增加 fallback 链

```
策略优先级:
  Level 1: LLM 回复含 "全部完成" 或 "第N题/共N题"
  Level 2: OCR 文本中有 "一、选择题(共X题)" 等显式声明
  Level 3: 编号序列的 max() - min() + 1，跳过缺失
  Level 4: _session_answered_count + 2（防负向）
  Level 5: 当前 25 道硬上限
```

**改动文件**：`docker/platform/provider_api.py` — `_tutor_chat_core()` 完成检测段

---

## 9. 实施路线图

### 9.1 优化项汇总

| 编号 | 优化项 | 优先级 | 改动量 | 收益 | 改动文件 |
|------|--------|--------|--------|------|----------|
| P0-1 | 渐进式反馈 | 🔴 P0 | ~30行 | 消除等待焦虑 | `weixin.py` |
| P0-2 | 年龄段语气 | 🔴 P0 | ~50行+数据 | 年段核心适配 | `provider_api.py` |
| P0-3 | 正向激励 | 🔴 P0 | ~20行 prompt | 维持学习动力 | `provider_api.py` |
| P0-4 | 进度可见 | 🔴 P0 | ~15行 | 减少未知焦虑 | `provider_api.py` |
| P1-5 | 信号词扩展 | 🟡 P1 | ~20行 | 暂停/恢复友好 | `weixin.py` |
| P1-6 | 错误降级 | 🟡 P1 | ~15行 prompt | 减少挫败感 | `provider_api.py` |
| P1-7 | OCR友好引导 | 🟡 P1 | ~20行 | 拍照失败引导 | `provider_api.py` |
| P2-8 | DeepSeek重试 | 🟢 P2 | ~10行 | 稳定性提升 | `provider_api.py` |
| P2-9 | 卡题超时 | 🟢 P2 | ~25行 | 防卡住 | `weixin.py` |
| P2-10 | 题数估算 | 🟢 P2 | ~20行 | 完成检测准确 | `provider_api.py` |

### 9.2 分阶段建议

**第一轮（P0，孩子体验核心）**：
1. P0-1 渐进式反馈
2. P0-2 年龄段语气
3. P0-3 正向激励
4. P0-4 进度可见

**第二轮（P1，教学流畅性）**：
5. P1-5 信号词扩展
6. P1-6 错误降级
7. P1-7 OCR友好引导

**第三轮（P2，稳定性打磨）**：
8. P2-8 DeepSeek重试
9. P2-9 卡题超时
10. P2-10 题数估算

---

## 10. 当前系统核心机制对照表

### 10.1 教学科学 — 三层模型

| 层次 | 描述 | 当前实现 |
|------|------|----------|
| 苏格拉底引导（每次交互） | 展示题目→引导提问→孩子回答→评判→讲解 | ✅ SOUL.md `_TEACHER_SOUL` |
| 分层引导策略（同题多轮） | 方向引导→方法提示→完整解析 | ✅ prompt 指令 |
| 艾宾浩斯间隔复习（跨时间） | 掌握度按间隔到期复习 | ✅ `schedule_review()` |

### 10.2 掌握度追踪

| 机制 | 实现位置 |
|------|----------|
| 掌握度 JSON 存储 | `domains/tutoring/mastery.py` → `/data/mastery/` |
| 答案标记解析 | `_tutor_chat_core()` → `_ANSWER_KEY_RE` / `_KP_ID_RE` |
| 掌握度更新 | `update_mastery(kp_id, correct, question, user_answer, correct_answer)` |
| 薄弱点检测 | `weak_points(learner_id)` → level < 0.6 |
| Ebbinghaus 复习调度 | `schedule_review()` → 1/3/7/14/30 天间隔 |
| 同类题巩固 | `_trigger_practice_if_needed()` → 同KPI连续2错 |
| 强化试卷自动生成 | `_auto_generate_exam()` → 薄弱点≥3 + 24h冷却 |

### 10.3 微信实时性保障

| 措施 | 参数 | 位置 |
|------|------|------|
| DT WS 响应超时 | 30s | `_DTTutorSession.send_and_recv()` |
| 锁超时(DT教学) | 5s → 切云端 | `_tutor_chat_core()` |
| 锁超时(HA OCR) | 60s | `api_llm_acquire(timeout)` |
| OCR 并发 | `Semaphore(2)` | 全局 |
| WS 空闲清理 | 每5分钟清理 >30分钟空闲 | `_dt_session_cleanup_loop()` |
| 教学会话过期 | 2h 无活动 | `_route_child_message()` |
| 上下文持久化 | JSON → 磁盘 → 重启恢复 | `_save_context_to_disk()` |
| iLink 窗口保障 | `_running_teachings` 提前释放 | `_run_teaching_flow()` |

### 10.4 并发防护体系

| 锁 | 范围 | TTL | 用途 |
|----|------|-----|------|
| `_running_teachings` | per-learner | 教学流执行期间 | 防止同一 learner 重复教学 |
| `_learner_locks` | per-learner | 无TTL (asyncio.Lock) | 防止 learner 级别竞态 |
| `_soul_global_lock` | 全局 | 无TTL (asyncio.Lock) | SOUL.md 写入序列化 |
| `_soul_version` | 全局 | 递增计数器 | 检测过期 SOUL.md 写入 |
| `_llm_lock` | 全局 | TTL 120s | 本地 NPU 访问序列化 |
| `_ocr_semaphore` | 全局 | Semaphore(2) | NPU OOM 防护 |

---

## 变更日志

| 日期 | 变更 |
|------|------|
| 2026-05-31 | v1.0 初版 |
| 2026-05-31 | v1.1 修复进度条标签 `第5/31题` → `Q5/31`：原格式含 `第+数字` 被 weixin.py 题号提取 regex `r"第\d+[题/]"` 错误匹配，导致 session 的 question_num 被进度条数字覆盖，后续教学轮次按错误题号构建 LLM payload 造成卡住无反馈 |
| 2026-05-31 | v1.2 ①移除 EVALUATE_ANSWER 阶段平台注入的 `═══ ✅ 正确答案 ═══` 分隔线（LLM 正文已包含正确答案，避免重复）；②移除 weixin.py 逐页 OCR 进度消息及"正在出题"中间消息，仅保留初始确认+最终题目，实现"1张卡片"体验 |

> **文档版本**: v1.2
> **审查日期**: 2026-05-31
> **基于代码**: provider_api.py (7054行), weixin.py (2619行), deeptutor-guided-teaching.patch (822行), hermes-wechat-vendor.patch (554行), mastery.py (361行)
