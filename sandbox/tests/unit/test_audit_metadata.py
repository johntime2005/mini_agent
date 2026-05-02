"""Session 元数据 + 审计日志测试。

覆盖目标 2 的关键属性：

1. ``create_session`` 返回的对象带 ``created_at``/``status``/``owner``/
   ``resource_usage``，且 ``owner`` 能透传。
2. ``SandboxService.execute`` 完整流程后，session 的 ``status`` 变为
   ``idle``、``resource_usage`` 累计了 ``executions/duration_ms``。
3. ``audit_log`` 在 ``exec.start``/``exec.end`` 都被触发。
4. 策略拒绝时 ``policy.reject`` 审计事件被触发，原异常仍向上抛出。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from mini_agent_sandbox.errors import CommandNotAllowedError
from mini_agent_sandbox.types import SandboxRequest


# ---------------------------------------------------------------------------
# 工具：捕获 audit logger 的事件
# ---------------------------------------------------------------------------
class _AuditCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.events: list[tuple[str, dict]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.events.append((getattr(record, "audit_event", record.msg),
                            getattr(record, "audit_fields", {})))


@pytest.fixture
def audit_capture():
    h = _AuditCapture()
    lg = logging.getLogger("mini_agent_sandbox.audit")
    prev = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    try:
        yield h
    finally:
        lg.removeHandler(h)
        lg.setLevel(prev)


# ---------------------------------------------------------------------------
# 元数据
# ---------------------------------------------------------------------------
def test_create_session_has_metadata(session_manager):
    session = session_manager.create_session(owner="alice")
    assert session.owner == "alice"
    assert session.status == "created"
    assert isinstance(session.created_at, datetime)
    assert session.created_at.tzinfo is not None  # 带时区，避免歧义
    assert session.resource_usage == {}


def test_get_session_keeps_metadata(session_manager):
    """get_session 应返回内存里同一个对象，元数据不丢。"""
    s1 = session_manager.create_session(owner="bob")
    s2 = session_manager.get_session(s1.session_id)
    assert s2.owner == "bob"
    assert s2.created_at == s1.created_at


# ---------------------------------------------------------------------------
# 审计日志：成功执行
# ---------------------------------------------------------------------------
def test_execute_emits_audit_events_and_accumulates_usage(service, audit_capture):
    session = service.create_session(owner="alice")
    (session.workspace_dir / "ok.py").write_text("print('ok')\n", encoding="utf-8")
    req = SandboxRequest(session_id=session.session_id, command="python", args=["ok.py"], timeout_ms=5000)

    result = service.execute(req)

    assert result.success is True
    events = [e for e, _ in audit_capture.events]
    # 至少包含 create + start + end 三个里程碑事件
    assert "session.create" in events
    assert "exec.start" in events
    assert "exec.end" in events

    # 元数据被回填：状态变 idle、资源累积
    refreshed = service.session_manager.get_session(session.session_id)
    assert refreshed.status == "idle"
    assert refreshed.resource_usage.get("executions") == 1
    assert refreshed.resource_usage.get("duration_ms", 0) >= 0


# ---------------------------------------------------------------------------
# 审计日志：策略拦截
# ---------------------------------------------------------------------------
def test_policy_rejection_emits_audit(service, audit_capture):
    session = service.create_session()
    req = SandboxRequest(session_id=session.session_id, command="bash", args=["-c", "echo x"], timeout_ms=1000)

    with pytest.raises(CommandNotAllowedError):
        service.execute(req)

    events = [e for e, _ in audit_capture.events]
    assert "policy.reject" in events
    # 不应触发 exec.start / exec.end
    assert "exec.start" not in events
    assert "exec.end" not in events
