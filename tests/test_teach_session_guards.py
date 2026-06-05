"""Test anti-spam guards in TeachSessionStore.create().

Verifies: file locking, cooldown, max-pending cap, title dedup, bypass_guards.
"""

import time
import tempfile
from pathlib import Path

import pytest

from tutor_platform.teach_session import TeachSessionStore, MAX_PENDING_PER_LEARNER


@pytest.fixture
def store():
    """Create a store with a temp directory."""
    with tempfile.TemporaryDirectory() as tmp:
        s = TeachSessionStore(data_dir=tmp)
        yield s


LEARNER = "test_learner"


def _make(store, title="测试卷", source="wechat", bypass=False, learner=LEARNER):
    return store.create(
        learner_id=learner,
        source=source,
        ocr_text=f"这是{title}的内容",
        title=title,
        bypass_guards=bypass,
    )


def _clear_cooldown(store, learner=LEARNER):
    """Reset cooldown so we can test other guards without cooldown interference."""
    store._last_create.pop(learner, None)


class TestCreateBasic:
    def test_create_basic(self, store):
        s = _make(store)
        assert s.session_id.startswith("ts_")
        assert s.status == "pending"
        assert s.learner_id == LEARNER
        assert s.title == "测试卷"


class TestCooldownGuard:
    def test_cooldown_blocks_rapid_create(self, store):
        _make(store, title="卷A")
        with pytest.raises(RuntimeError, match="throttled"):
            _make(store, title="卷B")

    def test_bypass_skips_cooldown(self, store):
        _make(store, title="卷A")
        s = _make(store, title="卷B", bypass=True)
        assert s.title == "卷B"


class TestMaxPendingGuard:
    def test_max_pending_blocks_creation(self, store):
        for i in range(MAX_PENDING_PER_LEARNER):
            _clear_cooldown(store)
            _make(store, title=f"卷{i}")
        _clear_cooldown(store)
        with pytest.raises(RuntimeError, match="Too many pending"):
            _make(store, title="溢出的卷")

    def test_bypass_skips_max_pending(self, store):
        for i in range(MAX_PENDING_PER_LEARNER):
            _clear_cooldown(store)
            _make(store, title=f"卷{i}")
        s = _make(store, title="溢出的卷", bypass=True)
        assert s.title == "溢出的卷"


class TestTitleDedup:
    def test_title_dedup_returns_existing(self, store):
        s1 = _make(store, title="重复卷", source="wechat")
        _clear_cooldown(store)
        s2 = _make(store, title="重复卷", source="wechat")
        assert s2.session_id == s1.session_id

    def test_different_title_creates_new(self, store):
        s1 = _make(store, title="卷A")
        _clear_cooldown(store)
        s2 = _make(store, title="卷B")
        assert s2.session_id != s1.session_id


class TestFileLock:
    def test_file_lock_released_after_create(self, store):
        lock_path = store._lock_path(LEARNER)
        _make(store)
        assert not lock_path.exists(), f"Lock file {lock_path} leaked"

    def test_file_lock_released_on_error(self, store):
        for i in range(MAX_PENDING_PER_LEARNER):
            _clear_cooldown(store)
            _make(store, title=f"卷{i}")
        _clear_cooldown(store)
        lock_path = store._lock_path(LEARNER)
        with pytest.raises(RuntimeError):
            _make(store, title="溢出的卷")
        assert not lock_path.exists(), f"Lock file {lock_path} leaked on error"


class TestCooldownCleanup:
    def test_cooldown_dict_cleanup(self, store):
        for i in range(110):
            store._last_create[f"learner_{i}"] = time.time() - 3600
        _make(store, learner="new_learner")
        assert len(store._last_create) <= 100


class TestExpireStale:
    def test_expire_stale_marks_expired(self, store):
        from tutor_platform.teach_session import TeachSession
        import uuid

        now = time.time()
        expired = TeachSession(
            session_id=f"ts_{uuid.uuid4().hex[:12]}",
            learner_id="test_expire",
            status="pending",
            source="wechat",
            ocr_text="test",
            source_file="",
            total_questions=0,
            current_question=0,
            first_question="",
            created_at=now - 100000,
            expires_at=now - 1,
        )
        store.save(expired)

        active = TeachSession(
            session_id=f"ts_{uuid.uuid4().hex[:12]}",
            learner_id="test_expire",
            status="active",
            source="wechat",
            ocr_text="test",
            source_file="",
            total_questions=0,
            current_question=0,
            first_question="",
            created_at=now,
            expires_at=now + 3600,
        )
        store.save(active)

        store.expire_stale()

        reloaded_expired = store.get(expired.session_id)
        assert reloaded_expired is not None
        assert reloaded_expired.status == "expired"

        reloaded_active = store.get(active.session_id)
        assert reloaded_active.status == "active"
