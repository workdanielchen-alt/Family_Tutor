# Implementation Plan: Guide Teaching Normalization (Revised)

## Phase 1 — TeachSession Store

**File:** `tutor_platform/teach_session.py` (NEW)

```python
@dataclass
class TeachSession:
    session_id: str          # ts_xxx
    learner_id: str
    status: str              # pending | active | completed
    ocr_text: str
    source_file: str
    source: str              # "wechat" | "webui"
    total_questions: int
    current_question: int    # 0 before first question
    first_question: str      # cached first question text
    created_at: float
    expires_at: float
```

- `get_pending(learner_id)` — 待教学任务
- `create()`, `get()`, `save()` — 标准 CRUD

## Phase 2 — Backend API

**File:** `docker/platform/provider_api.py`

### 2a. `POST /api/teach/start`

```
微信: { ocr_text, learner_id, source_file }
WebUI: { file_base64, filename, learner_id }
→ 创建 TeachSession
→ _tutor_core_chat(message="", learner_id, context=ocr_text, mode="guide")
→ 提取第一题 → 缓存到 session.first_question
→ 返回 { ok, session_id, first_question, total_questions }
```

### 2b. `POST /api/teach/continue`

```
{ teach_session_id, message, learner_id }
→ Load session
→ _tutor_core_chat(message, learner_id, context="", mode="guide")
→ 更新 session.current_question
→ 如果 done → session.status = "completed"
→ 返回 { ok, reply, current, total_questions, done }
```

### 2c. `GET /api/teach/pending/{learner_id}`

```
→ TeachSessionStore.get_pending(learner_id)
→ 返回列表 [{ session_id, source, total_questions, current_question, created_at }]
```

### 2d. `GET /api/teach/session/{session_id}`

```
→ Load session
→ 返回 { session_id, source, first_question, total_questions, current_question, status }
```

### 2e. Delete (cleanup)

- Remove `create_quiz` extraction + handling block in `api_process_file`
- Remove `_generate_quiz_from_ocr` function
- Remove `_fallback_llm_extract` function
- Remove `api_quiz_create_from_ocr` endpoint (if exists)
- Remove `api_quiz_pending` endpoint (or keep for compat)

## Phase 3 — Frontend API

**File:** `web/lib/platform-api.ts`

- `startTeach(params)` → `POST /api/platform/teach/start`
- `continueTeach(params)` → `POST /api/platform/teach/continue`
- `fetchPendingTeach(learnerId)` → `GET /api/platform/teach/pending/{learnerId}`
- `fetchTeachSession(sessionId)` → `GET /api/platform/teach/session/{sessionId}`

## Phase 4 — WebUI Chat Page

**File:** `web/app/(app)/chat/[[...sessionId]]/page.tsx`

### 4a. File upload → teach

When a file is attached and user sends:
1. Convert file to base64
2. Call `startTeach({ file_base64, filename, learner_id })`
3. Display returned `first_question` as a chat message
4. Enter "teach mode" (set `teachSessionId` state)

### 4b. Answer submission in teach mode

When `teachSessionId` is set:
1. Send to `continueTeach()` instead of WebSocket
2. Display reply as chat message
3. If `done`, exit teach mode, switch back to WS

### 4c. Show pending teach tasks

On the welcome screen (or pending tasks area):
1. Poll `fetchPendingTeach(learnerId)` 
2. Show cards: "📚 家长发来的教学任务" with source badge
3. Click → call `fetchTeachSession(sessionId)` → enter teach mode

## Phase 5 — WeChat Gateway

**File:** `vendor/hermes-agent/gateway/platforms/weixin.py` (PATCH)

### 5a. Remove create_quiz

- Remove `form.add_field("create_quiz", "1")`
- Remove the quiz card sending block (our previous patch)

### 5b. Add teach start

- After OCR succeeds, POST `/api/teach/start` with ocr_text
- Log result, send simple WeChat message: "已收到，让孩子在电脑上看看吧"

## Phase 6 — Cleanup

- `tutor_platform/quiz_session.py` — DELETE
- All pending QuizSession JSON files — DELETE (test only)

## Implementation Order

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6
(store)   (API)     (API lib) (WebUI)   (WeChat) (cleanup)
```

No blockers identified. Each phase independently testable.
