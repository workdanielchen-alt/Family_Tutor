"""TeachSession 存储模块

管理引导式教学会话生命周期:
  create → pending → active → completed | expired

数据以 JSON 文件持久化到 TEACH_SESSIONS_DIR。

由家长微信发题或 WebUI 上传文件触发创建，
_tutor_chat_core (mode=guide) 驱动逐题教学。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# ── 配置 ────────────────────────────────────────────────────────

TEACH_SESSIONS_DIR = Path(os.getenv("TEACH_SESSIONS_DIR", "/data/teach_sessions"))
SESSION_TTL_HOURS = int(os.getenv("TEACH_SESSION_TTL_HOURS", "48"))

# ── 数据模型 ────────────────────────────────────────────────────


@dataclass
class TeachSession:
    session_id: str          # ts_xxx
    learner_id: str
    status: str              # pending | active | completed | expired
    source: str              # "wechat" | "webui"
    ocr_text: str            # OCR 全文
    source_file: str         # 原始文件名
    total_questions: int     # 估算总题数
    current_question: int    # 当前进度（0 = 未开始）
    first_question: str      # 缓存的第一题文本
    dt_session_id: str = ""  # 绑定的 DT 聊天 session ID
    created_at: float = 0.0
    expires_at: float = 0.0
    completed_at: Optional[float] = None

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


# ── 序列化辅助 ─────────────────────────────────────────────────


def _serialize(obj):
    if isinstance(obj, TeachSession):
        return asdict(obj)
    return obj


def _deserialize_session(d: dict) -> TeachSession:
    return TeachSession(**{k: v for k, v in d.items() if k in TeachSession.__dataclass_fields__})


# ── 存储 ────────────────────────────────────────────────────────


class TeachSessionStore:
    """文件型 TeachSession 持久化存储。"""

    def __init__(self, data_dir: Path | str = TEACH_SESSIONS_DIR):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.data_dir / f"{session_id}.json"

    def create(
        self,
        learner_id: str,
        source: str,
        ocr_text: str,
        source_file: str = "",
        total_questions: int = 0,
        first_question: str = "",
        dt_session_id: str = "",
    ) -> TeachSession:
        """创建新的教学会话。"""
        now = time.time()
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
        )
        self.save(session)
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


# ── 全局单例 ────────────────────────────────────────────────────

_store: Optional[TeachSessionStore] = None


def get_store() -> TeachSessionStore:
    global _store
    if _store is None:
        _store = TeachSessionStore()
    return _store
