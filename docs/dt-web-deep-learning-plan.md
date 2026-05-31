# DT Web UI 深度学习 — 全功能模块串联方案

> 基于 DT 后端 API（8001）、MCP 工具集（platform:8100）、掌握度系统（mastery.py）的全链路分析。

---

## 1. 现状：DT Web UI 功能分布

### 1.1 页面清单

| 页面 | 路径 | 能力 | 孩子使用频率 |
|------|------|------|------------|
| **学习空间** | `/space` | 首页仪表盘（聊天历史/记忆/笔记本/题目/技能） | 高频 |
| **聊天** | `/chat/[...sessionId]` | 与 TutorBot 对话 | 中频 |
| **知识库** | `/knowledge` | 浏览已入库的教材/课件 | 低频 |
| **笔记本** | `/notebook` | 笔记管理 | 低频 |
| **书籍** | `/book` | 互动教材阅读（含嵌入测验） | 中频 |
| **记忆** | `/memory` | 查看/编辑记忆数据 | 低频 |
| **设置** | `/settings` | 模型/知识库/技能配置 | 低频 |

### 1.2 后端能力（MCP 工具）

| 工具 | 能力 | 对应 P0/P1 功能 |
|------|------|-----------------|
| `generate_practice` | 根据错题生成针对性练习 | F13 同类题巩固 |
| `generate_exam_paper` | 根据学情生成完整强化试卷 | F15 强化试卷 |
| `quiz_review` | 错题回顾 | F18 错题本 |
| `record_quiz_result` | 记录答题结果到掌握度 | F05 掌握度追踪 |
| `deep_solve` | 深度解题（分步解析） | F23 深度解题 |
| `vision_solve` | 拍照解题 | F24 拍照解题 |
| `update_memory` | 更新学习者画像 | — |
| `question_notebook_list` | 列出题目笔记 | — |
| `kb_search` | 知识库语义搜索 | F22 知识库搜索 |

### 1.3 孩子从微信到 Web 的断裂点

```
微信教学（日常）                         Web 深度学习（周末）
─────────────────                       ─────────────────
发卷 → AI 逐题引导                        打开浏览器 → ？
答对/答错 → 掌握度更新                        [这里断了]
完成 → 薄弱点总结                           孩子不知道该点哪里
```

**核心问题**：Web UI 把"学习空间""知识库""笔记本""聊天"做成独立页面，但孩子打开 Web 端后不知道该先做什么、各页面之间怎么串联、学了半天的成果怎么和微信上的学习记录打通。

---

## 2. 设计方案：从"冰冷工具"到"沉浸学习流程"

### 2.1 总体原则

1. **微信是发题入口，Web 是深度学习出口** — 不重复微信的能力
2. **每次打开 Web 都有清晰目标** — 不给空荡荡的仪表盘
3. **所有功能围绕"薄弱点消除"展开** — 掌握度雷达图是核心导航
4. **操作不超过 3 步就能开始深度学习** — 减少认知负担

### 2.2 新首页：学习仪表盘（整合方案）

```
┌─────────────────────────────────────────────────────┐
│   👋 下午好，惠子！                                   │
│   今天已学 12 道题 · 正确率 67%                       │
│                                                       │
│   ┌─────────────────────────────────────┐            │
│   │    知识点掌握度雷达图                │            │
│   │       数学  ████████░░ 80%          │            │
│   │       物理  ██████░░░░ 60%          │            │
│   │       化学  ████░░░░░░ 40%  ←薄弱   │  ← 点击薄弱点
│   │       语文  ███████░░░ 75%          │     直接进入
│   │       英语  █████████░ 90%          │     专项训练
│   └─────────────────────────────────────┘            │
│                                                       │
│   ┌─ 今日待办 ───────────────────────────────────┐   │
│   │  🔴 化学薄弱点 3 个 → 生成强化试卷            │   │
│   │  🟡 到期复习 2 个 → 立即复习                  │   │
│   │  📝 错题本 5 道待回顾 → 开始回顾              │   │
│   └──────────────────────────────────────────────┘   │
│                                                       │
│   ┌─ 快速开始 ───────────────────────────────────┐   │
│   │  [ 生成练习 ] [ 错题回顾 ] [ 深度解题 ]        │   │
│   └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 2.3 三大深度学习流程

#### 流程 A：薄弱点专项训练（核心路径）

```
起点：雷达图 / 今日待办
  │
  ├─ 点击薄弱知识点 → 查看详情
  │    ├─ 知识点名称（如"化学/物质的变化"）
  │    ├─ 掌握度：40%（已答 5 题，正确 2 题）
  │    ├─ 近期错题（最近 3 道）
  │    └─ 建议行动：
  │         [ 生成 3 道针对性练习 ]   ← 调用 generate_practice
  │         [ 加入今日强化试卷 ]      ← 调用 generate_exam_paper
  │
  ├─ 进入练习 → 逐题作答
  │    ├─ 每题答完立刻显示结果 + 解析
  │    ├─ 全部完成后显示正确率 + 知识点掌握度变化
  │    └─ 薄弱点列表同步更新
  │
  └─ 回到仪表盘 → 掌握度自动刷新
```

#### 流程 B：强化试卷模拟考

```
起点：今日待办 / 快速开始
  │
  ├─ "生成强化试卷"
  │    ├─ 自动覆盖所有薄弱知识点（掌握度 < 0.6）
  │    ├─ 选择题 40% + 填空题 30% + 解答题 30%
  │    ├─ 难度：基础 50% + 中等 35% + 拔高 15%
  │    └─ 限时模式：可选 30/45/60 分钟
  │
  ├─ 逐题作答（Web 端大屏体验）
  │    ├─ 选择题：点击选项，即时反馈
  │    ├─ 填空题：输入答案，提交后显示正误
  │    ├─ 解答题：输入文字/公式，AI 批改评分
  │    └─ 每题都有详细解析 + 知识点归因
  │
  └─ 完成 → 生成报告
       ├─ 总得分 + 各知识点正确率
       ├─ 掌握度更新前后对比
       ├─ 错题自动加入错题本
       └─ 建议下一步（多练习薄弱点 / 休息 / 回到首页）
```

#### 流程 C：错题本系统回顾

```
起点：今日待办 / 快速开始
  │
  ├─ "错题回顾"
  │    ├─ 按知识点筛选错题
  │    ├─ 按日期/次数排序
  │    ├─ 每道题显示：原题 + 学生答案 + 正确答案 + 解析
  │    └─ [重新作答] 按钮
  │
  ├─ 重新作答
  │    ├─ 答对 → 标记为已掌握，从错题本移出
  │    ├─ 再次答错 → 标记为需重点复习，出同类题
  │    └─ 结果反馈到掌握度系统
  │
  └─ 同类题巩固
       └─ 调用 generate_practice 生成 3 道同类变式题
```

### 2.4 微信 ↔ Web 数据打通

```
微信教学                          Web 深度学习
────────                          ────────────
答第5题 ✓ → 掌握度 +5%  ──────→  雷达图实时更新
答第5题 ✗ → 错题记录     ──────→  错题本同步显示
到期复习提醒     ──────→  今日待办显示"到期复习 2 个"
薄弱点 ≥ 3 个  ──────→  自动推荐"生成强化试卷"
```

**关键：两个入口共享同一份 `mastery JSON`**（`/data/mastery/`），不需要额外同步。

---

## 3. 实现路径

### 3.1 Phase 1：新仪表盘（MVP）

**目标**：让 Web 首页不再是空页面，孩子打开就知道该做什么

| 组件 | 数据来源 | 实现方式 |
|------|----------|----------|
| 今日概览 | `generate_daily_report()` | 后端 API → 前端展示 |
| 掌握度雷达图 | `get_mastery_summary()` | 前端 Chart.js 雷达图 |
| 今日待办 | `weak_points()` + `get_due_reviews()` + `get_wrong_answers()` | 后端聚合 API → 前端列表 |
| 快速开始按钮 | 链接到现有页面 | 纯前端路由 |

**改动范围**：
- `web/app/(app)/space/page.tsx` — 重构首页
- 新增后端聚合 API `GET /api/learner/dashboard?learner_id=xxx`

### 3.2 Phase 2：薄弱点专项训练

**目标**：点击薄弱点 → 生成练习 → 逐题作答 → 反馈 → 回到仪表盘，形成闭环

| 步骤 | 实现 |
|------|------|
| 点击薄弱点 | 前端打开 `weak-point/[kp_id]` 页面 |
| 生成练习 | 调用 `POST /api/practice/generate`（委托 `generate_practice` MCP 工具） |
| 逐题作答 | `components/quiz/QuizViewer.tsx` 复用 |
| 记录结果 | `record_quiz_result` MCP 工具 |
| 更新掌握度 | `update_mastery()` |

**改动范围**：
- 新建 `web/app/(app)/space/weak-point/[kp_id]/page.tsx`
- 新建 `web/app/(app)/space/practice/session/[session_id]/page.tsx`

### 3.3 Phase 3：强化试卷

**目标**：完整模拟考体验，选择题/填空题/解答题三段式

| 步骤 | 实现 |
|------|------|
| 生成试卷 | `generate_exam_paper` MCP 工具 |
| 渲染试卷 | `QuizViewer.tsx` 扩展支持三段式 |
| 自动批改 | `record_quiz_result` + `update_mastery` |
| 报告生成 | 完成页聚合展示 |

### 3.4 Phase 4：错题本增强

**目标**：不只是一个列表，而是"回顾 → 重做 → 巩固"的完整流程

| 功能 | 实现 |
|------|------|
| 按知识点筛选 | 前端 `get_wrong_answers(kp_id)` |
| 重新作答 | 展开错题 → 输入答案 → 对比 |
| 同类题巩固 | `generate_practice(kp_id, count=3)` |

---

## 4. 技术实现细节

### 4.1 后端聚合 API

```
GET /api/learner/dashboard
参数: learner_id

返回:
{
  "today": {
    "total_questions": 12,
    "correct": 8,
    "accuracy": 0.67
  },
  "mastery": [
    {"kp_id": "化学/物质的变化", "level": 0.4, "total": 5, "correct": 2},
    ...
  ],
  "weak_points": [
    {"kp_id": "化学/物质的变化", "level": 0.4, "total": 5}
  ],
  "due_reviews": [
    {"kp_id": "数学/幂的运算", "level": 0.6, "due_date": "2026-05-31"}
  ],
  "wrong_answers_count": 5
}
```

### 4.2 前端组件地图

```
space/page.tsx              ← 新仪表盘
  ├─ TodayOverview           ← 今日概览卡片
  ├─ MasteryRadar            ← 掌握度雷达图
  ├─ TodoList                ← 今日待办列表
  └─ QuickActions            ← 快速开始按钮组

space/weak-point/[kp_id]/    ← 薄弱点详情
  ├─ page.tsx                ← 详情 + 行动入口

space/practice/session/      ← 练习会话
  └─ [session_id]/page.tsx   ← 逐题作答

space/exam/[exam_id]/        ← 强化试卷
  └─ page.tsx                ← 三段式试卷作答

space/review/                ← 错题回顾
  └─ page.tsx                ← 筛选 + 重做
```

### 4.3 Mastery 数据流

```
Web 作答 → record_quiz_result → platform MCP
                                    ↓
                              mastery.py (JSON)
                                    ↓
                          update_mastery(kp_id, correct, ...)
                                    ↓
                          掌握度 JSON 更新 → 下次 dashboard 查询即反映
```

---

## 5. Phase 1 实施计划（最小可行产品）

### 第 1 步：后端 dashboard API

```
新增 `GET /api/learner/dashboard` 在 provider_api.py 或 mcp_server.py
```

- 调用 `get_mastery_summary()` / `weak_points()` / `get_due_reviews()` / `get_wrong_answers()` / `generate_daily_report()`
- 返回聚合 JSON

### 第 2 步：前端仪表盘

```
重构 web/app/(app)/space/page.tsx
```

- 调用 `/api/learner/dashboard`
- 渲染雷达图（Chart.js / Recharts 轻量方案）
- 渲染待办列表
- 渲染快速操作按钮

### 第 3 步：薄弱点专项练习页面

```
新建 web/app/(app)/space/weak-point/[kp_id]/page.tsx
新建 web/app/(app)/space/practice/[session_id]/page.tsx
```

- 点击薄弱点 → 生成练习 → 逐题作答 → 记录结果

---

## 6. 现有可复用资源

| 资源 | 位置 | 无需改动 |
|------|------|----------|
| `QuizViewer.tsx` | `web/components/quiz/` | ✅ 选择题作答 UI |
| `QuizConfigPanel.tsx` | `web/components/quiz/` | ✅ 练习配置面板 |
| `VisualizationViewer.tsx` | `web/components/visualize/` | ✅ 可视化查看器 |
| `generate_practice` MCP | `mcp_server.py` | ✅ 练习生成 |
| `generate_exam_paper` MCP | `mcp_server.py` | ✅ 试卷生成 |
| `record_quiz_result` MCP | `mcp_server.py` | ✅ 结果记录 |
| `mastery.py` | `domains/tutoring/` | ✅ 掌握度存储 |
| `get_mastery_summary()` | `domains/tutoring/mastery.py` | ✅ 掌握度查询 |
| `weak_points()` | `domains/tutoring/mastery.py` | ✅ 薄弱点查询 |
| `get_wrong_answers()` | `domains/tutoring/mastery.py` | ✅ 错题查询 |
| `get_due_reviews()` | `domains/tutoring/mastery.py` | ✅ 复习到期查询 |

---

> **文档版本**: v1.0
> **日期**: 2026-05-31

## 实施记录

### 2026-05-31 已完成

**后端（已部署生效）**：
- `docker/platform/provider_api.py` — 引导式教学优化（年龄段语气/激励规则/分隔线/DeepSeek重试/WS超时60s/题数估算）
- `vendor/hermes-agent/gateway/platforms/weixin.py` — weixin侧优化（渐进式反馈/信号扩展/idle检测/死锁TTL/send超时）

**前端（需重建镜像）**：
- `web/app/(app)/space/page.tsx` — 首页从 ChatHistorySection 改为 LearningDashboardSection
- `web/lib/space-items.ts` — 侧边栏添加「Learning Progress」入口
- `web/next.config.js` — distDir 恢复 ./.next2

**文档**：
- `docs/guided-teaching-analysis.md` — 引导式教学全链路分析
- `docs/dt-web-deep-learning-plan.md` — Web 深度学习模块串联方案

**Git 提交**（GitHub: family_tutor main, 6 commits）：
- `e19df0e70` — self.send加15s超时 + 限流日志
- `9a3db6427` — space首页改为LearningDashboard
- `347cb1732` — 侧边栏添加学习进度入口
- `5383aa225` — DT Web深度学习串联方案文档
- `a06151722` — tutor_chat POST加90s硬超时
- `50773aa6c` — 改用试卷原本题号体系出题

### 前端生效条件

当前 Docker 镜像是生产构建（standalone server.js），volume mount 的源码不会被重新编译。需在有 Docker Hub 网络的环境下重建镜像：

```bash
python scripts/docker_compose.py build deeptutor
python scripts/docker_compose.py -f docker-compose.yml -f docker-compose.dev.yml up -d deeptutor
```
