"""SessionManager 并发限制相关测试。

覆盖目标 1 新增能力：

1. ``acquire_slot()`` 在槽位充足时是无副作用的上下文管理器；
2. 满载时 ``blocking=False`` 必须立即抛 ``ConcurrencyLimitError``；
3. 满载时 ``blocking=True, timeout=...`` 等不到槽位也必须抛错；
4. 离开 ``with`` 上下文后，槽位必须被正确释放（信号量计数恢复）。
"""

from __future__ import annotations

import threading
import time

import pytest

from mini_agent_sandbox.session import ConcurrencyLimitError, SessionManager


@pytest.fixture
def sm(tmp_path):
    """一个并发上限只有 2 的小容量 SessionManager，方便构造满载场景。"""
    return SessionManager(base_dir=tmp_path, max_concurrent_sessions=2)


def test_acquire_slot_allows_within_limit(sm):
    """槽位充足时，acquire_slot 应当无障碍地进入与退出上下文。"""
    with sm.acquire_slot():
        pass  # 占用一个槽位再正常释放


def test_acquire_slot_non_blocking_raises_when_full(sm):
    """槽位满时，``blocking=False`` 必须立即抛 ConcurrencyLimitError。"""
    # 先占满 2 个槽位（在后台线程里持有，主测试线程才能尝试再获取）。
    holders_started = threading.Barrier(3)  # 2 个 holder + 主线程
    release_event = threading.Event()

    def _hold():
        with sm.acquire_slot():
            holders_started.wait()
            release_event.wait(timeout=5)

    threads = [threading.Thread(target=_hold) for _ in range(2)]
    for t in threads:
        t.start()

    holders_started.wait()  # 确保 2 个槽位都被持有

    try:
        with pytest.raises(ConcurrencyLimitError):
            with sm.acquire_slot(blocking=False):
                pass  # 不应该进得来
    finally:
        release_event.set()
        for t in threads:
            t.join(timeout=5)


def test_acquire_slot_blocking_with_timeout_raises(sm):
    """槽位满时，阻塞带 timeout 的获取在超时后必须抛错。"""
    release_event = threading.Event()
    holders_started = threading.Barrier(3)

    def _hold():
        with sm.acquire_slot():
            holders_started.wait()
            release_event.wait(timeout=5)

    threads = [threading.Thread(target=_hold) for _ in range(2)]
    for t in threads:
        t.start()
    holders_started.wait()

    try:
        started = time.perf_counter()
        with pytest.raises(ConcurrencyLimitError):
            with sm.acquire_slot(blocking=True, timeout=0.2):
                pass
        elapsed = time.perf_counter() - started
        # 至少阻塞过设定的 timeout，证明确实尝试等待过。
        assert elapsed >= 0.15
    finally:
        release_event.set()
        for t in threads:
            t.join(timeout=5)


def test_acquire_slot_releases_on_exit(sm):
    """离开 ``with`` 后，槽位必须被释放，可以被下一个请求重新获取。"""
    # 连续 3 次串行获取，每次都应当成功（如果未释放，第 3 次会爆）。
    for _ in range(3):
        with sm.acquire_slot(blocking=False):
            pass
    # 再来一次完整占满 + 释放的循环
    with sm.acquire_slot():
        with sm.acquire_slot():
            pass
        # 此时只占 1 个槽位，应当还能再拿一个
        with sm.acquire_slot(blocking=False):
            pass
