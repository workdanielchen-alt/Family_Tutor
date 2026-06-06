"""TeachSession 存储模块

管理引导式教学会话生命周期:
  create → pending → active → completed | expired

数据以 JSON 文件持久化到 TEACH_SESSIONS_DIR。

由家长微信发题或 WebUI 上传文件触发创建，
_tutor_chat_core (mode=guide) 驱动逐题教学。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 配置 ────────────────────────────────────────────────────────

TEACH_SESSIONS_DIR = Path(os.getenv("TEACH_SESSIONS_DIR", "/data/teach_sessions"))
SESSION_TTL_HOURS = int(os.getenv("TEACH_SESSION_TTL_HOURS", "48"))

# ── Anti-spam 限制 ─────────────────────────────────────────────
MAX_PENDING_PER_LEARNER = 5   # 每个 learner 最多同时 pending 任务数
TITLE_DEDUP_WINDOW = 300      # 5 分钟内同标题视为重复（秒）
CREATE_COOLDOWN = 30          # 同一 learner 创建间隔（秒）

# ── 数据模型 ────────────────────────────────────────────────────


@dataclass
class TeachSession:
    session_id: str          # ts_xxx
    learner_id: str
    status: str              # pending | active | completed | expired
    source: str              # "wechat" | "webui" | "auto_generated"
    ocr_text: str            # OCR 全文
    source_file: str         # 原始文件名
    total_questions: int     # 估算总题数
    current_question: int    # 当前进度（0 = 未开始）
    first_question: str      # 缓存的第一题文本
    dt_session_id: str = ""  # 绑定的 DT 聊天 session ID
    created_at: float = 0.0
    expires_at: float = 0.0
    completed_at: Optional[float] = None
    # ── Task metadata fields (v7.0 unified task model) ──
    title: str = ""                   # 显示标题，如 "2024数学期中卷"
    task_type: str = ""               # "exam_paper" | "practice" | "auto_reinforce"
    correct_count: int = 0            # 已答对题数
    wrong_count: int = 0              # 已答错题数
    knowledge_points: str = ""        # 关联知识点，逗号分隔
    subject: str = ""                 # 学科 (math/physics/chemistry/english)
    past_questions: str = ""          # JSON: [{q_json, evaluation_json, user_answer}, ...] 已答题目缓存

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


# ── 序列化辅助 ─────────────────────────────────────────────────


def _serialize(obj):
    if isinstance(obj, TeachSession):
        return asdict(obj)
    return obj


def _deserialize_session(d: dict) -> TeachSession:
    """反序列化时自动补齐缺失字段（兼容旧数据）。"""
    fields = {k: v for k, v in d.items() if k in TeachSession.__dataclass_fields__}
    # Backward compatibility: derive task_type from source for old records
    if "task_type" not in fields or not fields["task_type"]:
        src = fields.get("source", "")
        if src == "auto_generated":
            fields["task_type"] = "auto_reinforce"
        elif src in ("wechat", "webui"):
            fields["task_type"] = "exam_paper"
    return TeachSession(**fields)


# ── 存储 ────────────────────────────────────────────────────────


class TeachSessionStore:
    """文件型 TeachSession 持久化存储。"""

    def __init__(self, data_dir: Path | str = TEACH_SESSIONS_DIR):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._last_create: dict[str, float] = {}  # learner_id → timestamp

    def _path(self, session_id: str) -> Path:
        return self.data_dir / f"{session_id}.json"

    def _lock_path(self, learner_id: str) -> Path:
        return self.data_dir / f"_create_lock_{learner_id}.lock"

    def _acquire_learner_lock(self, learner_id: str, timeout: float = 10.0) -> Path:
        """获取 per-learner 文件锁 (O_CREAT|O_EXCL 原子操作)。"""
        lock_path = self._lock_path(learner_id)
        deadline = time.time() + timeout
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.close(fd)
                return lock_path
            except FileExistsError:
                if time.time() > deadline:
                    raise TimeoutError(
                        f"Could not acquire create lock for learner {learner_id} "
                        f"within {timeout}s"
                    )
                time.sleep(0.05)

    def _release_learner_lock(self, lock_path: Path) -> None:
        """释放 per-learner 文件锁。"""
        try:
            os.unlink(str(lock_path))
        except OSError:
            pass

    def create(
        self,
        learner_id: str,
        source: str,
        ocr_text: str,
        source_file: str = "",
        total_questions: int = 0,
        first_question: str = "",
        dt_session_id: str = "",
        title: str = "",
        task_type: str = "",
        knowledge_points: str = "",
        subject: str = "",
        bypass_guards: bool = False,
    ) -> TeachSession:
        """创建新的教学会话 — 带竞态保护 + 去重 + 上限检查。

        Args:
            bypass_guards: True=显式用户操作，跳过 anti-spam 检查（上限/冷却/去重）。
                           文件锁始终生效，防止并发竞态。

        防护规则 (bypass_guards=False):
        1. 文件锁防止并发重复创建（始终生效）
        2. 同标题 5 分钟内去重
        3. 30 秒冷却期
        4. 每人最多 MAX_PENDING_PER_LEARNER 个 pending 任务
        """
        lock_path = self._acquire_learner_lock(learner_id)
        try:
            return self._create_locked(
                learner_id=learner_id,
                source=source,
                ocr_text=ocr_text,
                source_file=source_file,
                total_questions=total_questions,
                first_question=first_question,
                dt_session_id=dt_session_id,
                title=title,
                task_type=task_type,
                knowledge_points=knowledge_points,
                subject=subject,
                bypass_guards=bypass_guards,
            )
        finally:
            self._release_learner_lock(lock_path)

    def _create_locked(
        self,
        learner_id: str,
        source: str,
        ocr_text: str,
        source_file: str = "",
        total_questions: int = 0,
        first_question: str = "",
        dt_session_id: str = "",
        title: str = "",
        task_type: str = "",
        knowledge_points: str = "",
        subject: str = "",
        bypass_guards: bool = False,
    ) -> TeachSession:
        """锁保护下的实际创建逻辑。"""
        now = time.time()

        if not bypass_guards:
            # ── Guard 1: 冷却期检查 ──
            last_ts = self._last_create.get(learner_id, 0)
            elapsed = now - last_ts
            if elapsed < CREATE_COOLDOWN:
                logger.warning(
                    "Skip task create for %s: cooldown (%.1fs < %ds)",
                    learner_id, elapsed, CREATE_COOLDOWN,
                )
                raise RuntimeError(
                    f"Task creation throttled: {elapsed:.1f}s since last create "
                    f"(minimum {CREATE_COOLDOWN}s)"
                )

            # ── Guard 2: 上限检查 ──
            existing_pending = self.get_pending(learner_id, limit=MAX_PENDING_PER_LEARNER + 1)
            if len(existing_pending) >= MAX_PENDING_PER_LEARNER:
                logger.warning(
                    "Skip task create for %s: max pending (%d) reached",
                    learner_id, MAX_PENDING_PER_LEARNER,
                )
                raise RuntimeError(
                    f"Too many pending tasks ({len(existing_pending)} >= "
                    f"{MAX_PENDING_PER_LEARNER}) for learner {learner_id}"
                )

            # ── Guard 3: 标题去重 (5 分钟内同标题 + 同 source) ──
            if title:
                title_lower = title.strip().lower()
                for s in existing_pending:
                    s_title = (s.title or "").strip().lower()
                    if s_title == title_lower and s.source == source:
                        age = now - s.created_at
                        if age < TITLE_DEDUP_WINDOW:
                            logger.info(
                                "Skip duplicate task for %s: title=%r source=%r "
                                "(existing %s, %.0fs old)",
                                learner_id, title, source, s.session_id, age,
                            )
                            return s  # 返回已存在的，不重复创建

        # ── 通过所有 guard，创建 ──
        self._last_create[learner_id] = now

        # 清理过期的 _last_create 条目（避免内存泄漏）
        if len(self._last_create) > 100:
            cutoff = now - 3600
            self._last_create = {
                k: v for k, v in self._last_create.items() if v > cutoff
            }

        session = TeachSession(
            session_id=f"ts_{uuid.uuid4().hex[:12]}",
            learner_id=learner_id,
            status="pending",
            source=source,
            ocr_text=ocr_text,
            source_file=source_file,
            total_questions=total_questions,
            current_question=0,
            first_question=first_question,
            dt_session_id=dt_session_id,
            created_at=now,
            expires_at=now + SESSION_TTL_HOURS * 3600,
            title=title,
            task_type=task_type,
            knowledge_points=knowledge_points,
            subject=subject,
        )
        self.save(session)
        logger.info("Created TeachSession %s for %s: title=%r source=%r",
                     session.session_id, learner_id, title, source)
        return session

    def save(self, session: TeachSession):
        path = self._path(session.session_id)
        path.write_text(
            json.dumps(_serialize(session), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, session_id: str) -> Optional[TeachSession]:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return _deserialize_session(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def get_pending(self, learner_id: str, limit: int = 20) -> list[TeachSession]:
        """获取学习者未完成且未过期的 sessions，按创建时间倒序。"""
        now = time.time()
        result = []
        for f in sorted(
            self.data_dir.glob("ts_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("learner_id") != learner_id:
                continue
            status = data.get("status", "")
            if status not in ("pending", "active"):
                continue
            expires = data.get("expires_at", 0)
            if now > expires:
                continue
            session = _deserialize_session(data)
            result.append(session)
            if len(result) >= limit:
                break
        return result

    def get_all_pending(self, limit: int = 50) -> list[TeachSession]:
        """获取所有学习者的待教学 sessions，按创建时间倒序。"""
        now = time.time()
        result = []
        for f in sorted(
            self.data_dir.glob("ts_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            status = data.get("status", "")
            if status not in ("pending", "active"):
                continue
            expires = data.get("expires_at", 0)
            if now > expires:
                continue
            session = _deserialize_session(data)
            result.append(session)
            if len(result) >= limit:
                break
        return result

    def mark_completed(self, session_id: str) -> Optional[TeachSession]:
        session = self.get(session_id)
        if not session:
            return None
        session.status = "completed"
        session.completed_at = time.time()
        self.save(session)
        return session

    def mark_active(self, session_id: str) -> Optional[TeachSession]:
        session = self.get(session_id)
        if not session:
            return None
        if session.status == "pending":
            session.status = "active"
            self.save(session)
        return session

    def expire_stale(self):
        """定时任务：将所有过期的 active/pending session 标记为 expired。"""
        now = time.time()
        for f in self.data_dir.glob("ts_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            status = data.get("status", "")
            if status not in ("pending", "active"):
                continue
            expires = data.get("expires_at", 0)
            if now <= expires:
                continue
            session = _deserialize_session(data)
            session.status = "expired"
            self.save(session)

    def get_tasks_for_sessions(self, session_ids: list[str]) -> dict[str, dict]:
        """Batch lookup: map chat session_id → task metadata dict.
        
        Returns only pending/active sessions whose dt_session_id matches.
        """
        now = time.time()
        lookup: dict[str, dict] = {}
        id_set = set(session_ids) if session_ids else set()
        if not id_set:
            return lookup
        for f in sorted(
            self.data_dir.glob("ts_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            dt_sid = data.get("dt_session_id", "")
            if dt_sid not in id_set:
                continue
            status = data.get("status", "")
            if status not in ("pending", "active"):
                continue
            expires = data.get("expires_at", 0)
            if now > expires:
                continue
            session = _deserialize_session(data)
            lookup[dt_sid] = {
                "teach_session_id": session.session_id,
                "title": session.title or session.source_file or "未命名试卷",
                "task_type": session.task_type,
                "task_source": session.source,
                "total_questions": session.total_questions,
                "current_question": session.current_question,
                "correct_count": session.correct_count,
                "wrong_count": session.wrong_count,
                "status": session.status,
                "knowledge_points": session.knowledge_points,
                "subject": session.subject,
                "created_at": session.created_at,
                "expires_at": session.expires_at,
            }
        return lookup


# ── 全局单例 ────────────────────────────────────────────────────

_store: Optional[TeachSessionStore] = None


def get_store() -> TeachSessionStore:
    global _store
    if _store is None:
        _store = TeachSessionStore()
    return _store
