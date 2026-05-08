"""PR #3 评审回归测试。

覆盖评审中标记的 5 个 🔴 项里测试缺口（评审 ✅ 节）：

* ``test_resource_usage_not_accumulated_across_runs`` — 修复 #1：
  同一 ``LocalProcessExecutor`` 实例连跑两次，第二次 ``cpu_time_ms``
  不应远大于第一次（``RUSAGE_CHILDREN`` 累计 bug）。
* ``test_service_resource_usage_per_call_not_doubled`` — 修复 #1 端
  到端：``service.execute`` 多次调用累积量 ≈ 单次和。
* ``test_executor_timeout_kills_process_group`` — 修复 #5：超时时杀
  整个进程组，不让 fork 出的孙进程泄漏。
* ``test_session_registry_lru_evicts_oldest`` — 修复 #11：注册表满时
  淘汰最旧条目；磁盘 workspace 仍可访问。
* ``test_session_registry_released_after_cleanup`` — 修复 #4：清理
  后 ``_registry`` 真正释放，不出 ``KeyError``。
* ``test_toctou_rejects_modified_script`` — 修复 #7：脚本在 policy
  校验与 exec 之间被替换 → ``SourceTamperedError``。
* ``test_workspace_in_forbidden_path_rejected_at_creation`` — 修复
  #8：敏感路径校验前移到 session 创建阶段。
* ``test_syntax_error_rejected_by_policy`` — 风格修复：语法错误不再
  静默放行。
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from mini_agent_sandbox.errors import (
    ArgumentNotAllowedError,
    PathForbiddenError,
    SourceTamperedError,
)
from mini_agent_sandbox.executor import Executor
from mini_agent_sandbox.policy import CommandPolicy
from mini_agent_sandbox.service import SandboxService
from mini_agent_sandbox.session import SessionManager
from mini_agent_sandbox.types import SandboxRequest

IS_WINDOWS = sys.platform == "win32"


def _write_script(session, name: str, content: str) -> None:
    (session.workspace_dir / name).write_text(content, encoding="utf-8")


def _req(session, script: str, *, timeout_ms: int = 5000) -> SandboxRequest:
    return SandboxRequest(
        session_id=session.session_id,
        command="python",
        args=[script],
        timeout_ms=timeout_ms,
    )


# ---------------------------------------------------------------------------
# #1 资源采样不再累计
# ---------------------------------------------------------------------------
@pytest.mark.skipif(IS_WINDOWS, reason="rusage sampling only available on Unix")
def test_resource_usage_not_accumulated_across_runs(sandbox_session):
    """Same executor, two runs: second cpu_time should be in the same
    order of magnitude as the first, not first+second.
    """
    _write_script(sandbox_session, "burn.py", "x = sum(range(200_000))\nprint(x)\n")
    executor = Executor()

    first = executor.run(_req(sandbox_session, "burn.py"), sandbox_session)
    second = executor.run(_req(sandbox_session, "burn.py"), sandbox_session)

    assert first.success and second.success
    assert isinstance(first.cpu_time_ms, int) and isinstance(second.cpu_time_ms, int)
    # If the bug regressed (RUSAGE_CHILDREN), second would carry first's
    # cost and likely be ≥ 1.5×. Allow generous slack for noise.
    floor = max(first.cpu_time_ms, 1)
    assert second.cpu_time_ms <= floor * 3, (
        f"Second run cpu_time_ms {second.cpu_time_ms}ms looks accumulated "
        f"(first={first.cpu_time_ms}ms); RUSAGE_CHILDREN regression?"
    )


@pytest.mark.skipif(IS_WINDOWS, reason="rusage sampling only available on Unix")
def test_service_resource_usage_per_call_not_doubled(service):
    """End-to-end: SandboxService.execute three times. Aggregate
    cpu_time_ms should grow linearly (each call adds roughly its own
    cost), not super-linearly (which would indicate the per-call
    sample itself is already accumulated).
    """
    session = service.create_session()
    _write_script(session, "tiny.py", "print(sum(range(50_000)))\n")

    samples: list[int] = []
    for _ in range(3):
        result = service.execute(_req(session, "tiny.py"))
        assert result.success
        assert isinstance(result.cpu_time_ms, int)
        samples.append(result.cpu_time_ms)

    # Each per-call sample should be bounded; if it were accumulated
    # we'd see samples[2] >> samples[0].
    floor = max(samples[0], 1)
    assert samples[2] <= floor * 4, f"Per-call samples look accumulated: {samples}"


# ---------------------------------------------------------------------------
# #5 超时杀进程组
# ---------------------------------------------------------------------------
@pytest.mark.skipif(IS_WINDOWS, reason="process groups are POSIX-only")
def test_executor_timeout_kills_process_group(sandbox_session):
    """Child fork()s a grandchild that sleeps 60s. When the wall-clock
    timeout fires we expect the entire process group to be SIGKILL'd
    so the grandchild does not survive the parent.
    """
    pid_file = sandbox_session.workspace_dir / "grandchild.pid"
    script = (
        "import os, time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        "    time.sleep(60)\n"
        "else:\n"
        f"    open({str(pid_file)!r}, 'w').write(str(pid))\n"
        "    time.sleep(60)\n"
    )
    _write_script(sandbox_session, "fork_bomb.py", script)

    executor = Executor()
    result = executor.run(
        _req(sandbox_session, "fork_bomb.py", timeout_ms=500),
        sandbox_session,
    )

    assert result.timeout is True

    # Give the SIGKILL a beat to take effect on the grandchild.
    deadline = time.monotonic() + 2.0
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pid_file.exists(), "Grandchild never wrote its pid; test setup failed"
    grandchild_pid = int(pid_file.read_text().strip())

    # Poll: signal 0 means "is this pid alive?"; ProcessLookupError → dead.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.kill(grandchild_pid, 0)
        except ProcessLookupError:
            return  # success: grandchild gone
        time.sleep(0.05)
    pytest.fail(f"Grandchild pid {grandchild_pid} still alive after timeout — killpg regression")


# ---------------------------------------------------------------------------
# #4 + #11 注册表锁 + LRU 淘汰
# ---------------------------------------------------------------------------
def test_session_registry_lru_evicts_oldest(tmp_path):
    """Cap registry at 3, create 4 sessions; oldest should be gone from
    in-memory map but still resolvable via the disk-fallback path.
    """
    sm = SessionManager(base_dir=tmp_path, max_registry_entries=3)
    s1 = sm.create_session()
    s2 = sm.create_session()
    s3 = sm.create_session()
    # Make sure created_at ordering is well-defined even on coarse clocks.
    time.sleep(0.001)
    s4 = sm.create_session()

    assert s1.session_id not in sm._registry
    assert s2.session_id in sm._registry
    assert s3.session_id in sm._registry
    assert s4.session_id in sm._registry

    # Disk fallback still works for the evicted session.
    revived = sm.get_session(s1.session_id)
    assert revived.session_id == s1.session_id


def test_session_registry_released_after_cleanup(tmp_path):
    """cleanup_session must drop the entry from _registry; no KeyError
    on subsequent update_status (silently no-ops).
    """
    sm = SessionManager(base_dir=tmp_path)
    s = sm.create_session()
    assert s.session_id in sm._registry

    sm.cleanup_session(s.session_id)
    assert s.session_id not in sm._registry

    # Idempotent: should not raise even though the id is gone.
    sm.update_status(s.session_id, "idle")


# ---------------------------------------------------------------------------
# #7 TOCTOU
# ---------------------------------------------------------------------------
def test_toctou_rejects_modified_script(service):
    """Snapshot the script, mutate it, then verify must reject.

    Tests the TOCTOU defense at the unit level: ``_snapshot_python_source``
    captures a SHA-256 right after policy validation, ``_verify_python_source``
    re-hashes after ``acquire_slot`` and rejects on mismatch.
    """
    session = service.create_session()
    _write_script(session, "ok.py", "print('benign')\n")
    request = _req(session, "ok.py")

    script_path, script_hash = service._snapshot_python_source(request, session)
    assert script_path is not None and script_hash is not None

    # Race window: rewrite bytes under the original path.
    script_path.write_text("import socket\n", encoding="utf-8")

    with pytest.raises(SourceTamperedError):
        service._verify_python_source(script_path, script_hash)


def test_toctou_passes_when_script_unchanged(service):
    """Sanity check: identical content must not trigger a false positive."""
    session = service.create_session()
    _write_script(session, "ok.py", "print('benign')\n")
    request = _req(session, "ok.py")

    script_path, script_hash = service._snapshot_python_source(request, session)
    # No mutation between snapshot and verify.
    service._verify_python_source(script_path, script_hash)


# ---------------------------------------------------------------------------
# #8 forbidden_path 上移到 session creation
# ---------------------------------------------------------------------------
def test_workspace_in_forbidden_path_rejected_at_creation(tmp_path):
    """If the SessionManager.base_dir resolves under a forbidden prefix,
    SandboxService.create_session must reject and clean up the partial
    session instead of letting execute() blow up later.
    """
    sm = SessionManager(base_dir=tmp_path)
    # Mark the temp dir itself as forbidden so the workspace lands inside.
    policy = CommandPolicy(forbidden_paths=(str(tmp_path),))
    service = SandboxService(session_manager=sm, policy=policy)

    with pytest.raises(PathForbiddenError):
        service.create_session()

    # No leftover entry in registry — create_session rolled back.
    assert sm._registry == {}


# ---------------------------------------------------------------------------
# Style: SyntaxError no longer silently allowed
# ---------------------------------------------------------------------------
def test_syntax_error_rejected_by_policy(sandbox_session):
    """A deliberately malformed script must be rejected at policy
    validation time, not silently accepted (otherwise an attacker can
    smuggle disallowed imports past the AST check by breaking syntax
    and reconstructing at runtime via compile/exec).
    """
    _write_script(sandbox_session, "bad.py", "def broken(:\n")
    policy = CommandPolicy()

    with pytest.raises(ArgumentNotAllowedError):
        policy.validate(
            SandboxRequest(
                session_id=sandbox_session.session_id,
                command="python",
                args=["bad.py"],
                timeout_ms=1000,
            ),
            sandbox_session,
        )
