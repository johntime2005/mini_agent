from __future__ import annotations

import shutil
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from .audit import audit_log
from .errors import SessionNotFoundError
from .types import SandboxSession


class ConcurrencyLimitError(Exception):
    """超过并发会话上限时抛出。"""


class SessionManager:
    def __init__(
        self,
        base_dir: Path | None = None,
        max_concurrent_sessions: int = 5,
        max_registry_entries: int = 100,
    ) -> None:
        self.base_dir = base_dir or Path("/tmp/mini-agent-sandbox")
        self.sessions_dir = self.base_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # 用于限制 *同时执行* 的会话数量。注意：信号量不是限制
        # create_session 本身的速率，而是限制 ``acquire_slot()`` 进入
        # 临界区的并发量；service 层在执行代码时应包裹到 ``with
        # session_manager.acquire_slot():`` 里。
        self.max_concurrent_sessions = max_concurrent_sessions
        self._semaphore = threading.BoundedSemaphore(max_concurrent_sessions)
        # 内存注册表：保留元数据（created_at/status/owner/resource_usage）。
        # 长生命周期进程下需要容量上限，否则随 create_session 单调增长。
        # 满载时按 created_at 升序淘汰最旧条目（仅淘汰内存映射，磁盘
        # workspace 仍在，可走 get_session 的磁盘降级路径访问）。
        self.max_registry_entries = max_registry_entries
        self._registry: dict[str, SandboxSession] = {}
        # check-then-act 竞态保护：所有 _registry 读写都在锁内。
        self._registry_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 会话生命周期
    # ------------------------------------------------------------------
    def create_session(self, owner: str | None = None) -> SandboxSession:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session_root = self.sessions_dir / session_id
        workspace_dir = session_root / "workspace"
        logs_dir = session_root / "logs"
        workspace_dir.mkdir(parents=True, exist_ok=False)
        logs_dir.mkdir(parents=True, exist_ok=False)
        session = SandboxSession(
            session_id=session_id,
            root_dir=session_root,
            workspace_dir=workspace_dir,
            logs_dir=logs_dir,
            owner=owner,
        )
        evicted_id: str | None = None
        with self._registry_lock:
            if len(self._registry) >= self.max_registry_entries:
                evicted_id = min(
                    self._registry,
                    key=lambda sid: self._registry[sid].created_at,
                )
                del self._registry[evicted_id]
            self._registry[session_id] = session
        if evicted_id is not None:
            audit_log("session.evict", session_id=evicted_id, reason="registry_full")
        audit_log("session.create", session_id=session_id, owner=owner)
        return session

    def get_session(self, session_id: str) -> SandboxSession:
        # 优先用内存注册表（保留 created_at/status/owner 等元数据）；
        # 降级到磁盘探测以兼容旧流程或被 LRU 淘汰的旧会话。
        with self._registry_lock:
            cached = self._registry.get(session_id)
        if cached is not None:
            return cached
        session_root = self.sessions_dir / session_id
        workspace_dir = session_root / "workspace"
        logs_dir = session_root / "logs"
        if not workspace_dir.exists() or not logs_dir.exists():
            raise SessionNotFoundError(f"Sandbox session not found: {session_id}")
        return SandboxSession(
            session_id=session_id,
            root_dir=session_root,
            workspace_dir=workspace_dir,
            logs_dir=logs_dir,
        )

    def cleanup_session(self, session_id: str) -> None:
        session = self.get_session(session_id)
        shutil.rmtree(session.root_dir, ignore_errors=True)
        with self._registry_lock:
            self._registry.pop(session_id, None)
        audit_log("session.cleanup", session_id=session_id)

    def update_status(self, session_id: str, status: str) -> None:
        """更新内存中会话的 ``status`` 字段（不持久化）。"""
        with self._registry_lock:
            session = self._registry.get(session_id)
            if session is not None:
                session.status = status

    # ------------------------------------------------------------------
    # 并发控制
    # ------------------------------------------------------------------
    @contextmanager
    def acquire_slot(self, blocking: bool = True, timeout: float | None = None):
        """获取一个并发执行槽位。

        用法::

            with session_manager.acquire_slot(blocking=False):
                executor.run(...)

        - ``blocking=True``（默认）：阻塞直到获取到槽位。
        - ``blocking=False``：立即尝试，未成功则抛 ``ConcurrencyLimitError``。
        - ``timeout``：阻塞模式下的最大等待秒数；超时同样抛错。
        """
        if blocking and timeout is None:
            acquired = self._semaphore.acquire(blocking=True)
        else:
            acquired = self._semaphore.acquire(blocking=blocking, timeout=timeout)
        if not acquired:
            raise ConcurrencyLimitError(
                f"Reached max concurrent sessions: {self.max_concurrent_sessions}"
            )
        try:
            yield
        finally:
            self._semaphore.release()
