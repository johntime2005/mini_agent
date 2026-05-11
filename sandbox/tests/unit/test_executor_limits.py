"""Executor 资源限制相关的测试。

覆盖目标 1 新增能力的关键属性：

1. **资源使用采样**：成功执行后，``cpu_time_ms`` 和 ``memory_peak_bytes``
   都应被填充（Unix）或都为 None（Windows）。
2. **CPU 限制（仅 Unix）**：传入极小的 ``max_cpu_seconds`` 时，长时间
   占用 CPU 的脚本必须以非零退出码或被信号杀死。
3. **内存限制（仅 Unix）**：传入极小的 ``max_memory_bytes`` 时，大块内存
   分配的脚本必须失败。
4. **Windows 降级**：在 Windows 上传入限制不应抛异常，且仍能正常执行
   普通脚本。
5. **抽象接口**：``LocalProcessExecutor`` 必须是 ``BaseExecutor`` 的子类，
   保证未来 ``DockerExecutor`` 能用同一接口替换。
"""

from __future__ import annotations

import sys

import pytest

from mini_agent_sandbox.executor import (
    BaseExecutor,
    Executor,
    LocalProcessExecutor,
)
from mini_agent_sandbox.types import SandboxRequest

IS_WINDOWS = sys.platform == "win32"


def _write(sandbox_session, name: str, content: str) -> None:
    (sandbox_session.workdir / name).write_text(content, encoding="utf-8")


def _request(sandbox_session, script: str, *, timeout_ms: int = 5000) -> SandboxRequest:
    return SandboxRequest(
        session_id=sandbox_session.session_id,
        command="python",
        args=[script],
        timeout_ms=timeout_ms,
    )


# ---------------------------------------------------------------------------
# 抽象接口
# ---------------------------------------------------------------------------
def test_local_executor_implements_base_interface():
    """``LocalProcessExecutor`` 必须实现 ``BaseExecutor``。

    这是为目标 4（容器级沙箱预留接口）做的健全性检查：未来加入
    ``DockerExecutor`` 时，应当也继承自 ``BaseExecutor``，调用方仅依赖
    抽象接口即可平滑替换。
    """
    assert issubclass(LocalProcessExecutor, BaseExecutor)
    # 同名别名 ``Executor`` 必须指向同一个类，否则旧 import 会失效。
    assert Executor is LocalProcessExecutor


# ---------------------------------------------------------------------------
# 资源使用采样
# ---------------------------------------------------------------------------
def test_executor_reports_resource_usage(sandbox_session):
    """成功执行后，``SandboxResult`` 应包含资源使用信息。

    - Unix：``cpu_time_ms`` 和 ``memory_peak_bytes`` 都应是非负整数。
    - Windows：两个字段均为 ``None``（降级行为）。
    """
    _write(sandbox_session, "hi.py", "print('hi')\n")
    executor = Executor()

    result = executor.run(_request(sandbox_session, "hi.py"), sandbox_session)

    assert result.success is True
    if IS_WINDOWS:
        assert result.cpu_time_ms is None
        assert result.memory_peak_bytes is None
    else:
        assert isinstance(result.cpu_time_ms, int)
        assert result.cpu_time_ms >= 0
        assert isinstance(result.memory_peak_bytes, int)
        assert result.memory_peak_bytes > 0


# ---------------------------------------------------------------------------
# Windows 降级
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not IS_WINDOWS, reason="Windows-only graceful degradation test")
def test_executor_accepts_limits_on_windows_without_error(sandbox_session):
    """Windows 下传入资源限制不应抛异常；只是被忽略并记录警告。"""
    _write(sandbox_session, "hi.py", "print('ok')\n")
    executor = Executor(max_cpu_seconds=1, max_memory_bytes=64 * 1024 * 1024)

    result = executor.run(_request(sandbox_session, "hi.py"), sandbox_session)
    assert result.success is True
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# CPU / 内存限制（仅 Unix）
# ---------------------------------------------------------------------------
@pytest.mark.skipif(IS_WINDOWS, reason="resource module unavailable on Windows")
def test_executor_enforces_cpu_limit(sandbox_session):
    """传入 1 秒 CPU 限制 + 死循环脚本，必须以失败结束。

    具体表现可能是：
      - 进程因 SIGXCPU 被杀（returncode 为负）；或
      - 进程在限制下退出非 0；
    总之 ``success`` 必须为 False。
    """
    _write(sandbox_session, "burn.py", "while True:\n    pass\n")
    executor = Executor(max_cpu_seconds=1)

    # 给充足的 wall-clock 超时（5 秒），让 CPU 限制先触发。
    result = executor.run(_request(sandbox_session, "burn.py", timeout_ms=5000), sandbox_session)

    assert result.success is False


@pytest.mark.skipif(IS_WINDOWS, reason="resource module unavailable on Windows")
def test_executor_enforces_memory_limit(sandbox_session):
    """传入极小的内存限制 + 大内存分配脚本，必须以失败结束。"""
    _write(
        sandbox_session,
        "mem.py",
        # 申请 ~512MB；远超下面 32MB 的限制。
        "x = bytearray(512 * 1024 * 1024)\nprint(len(x))\n",
    )
    executor = Executor(max_memory_bytes=32 * 1024 * 1024)

    result = executor.run(_request(sandbox_session, "mem.py", timeout_ms=5000), sandbox_session)

    assert result.success is False
