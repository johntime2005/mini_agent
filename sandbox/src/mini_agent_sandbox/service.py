from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .audit import audit_log
from .errors import SandboxError
from .executor import Executor
from .policy import CommandPolicy
from .session import SessionManager
from .types import SandboxRequest, SandboxResult, SandboxSession


class SandboxService:
    """沙箱顶层服务。

    .. note::
       默认 ``SandboxService()`` **不启用** ``RLIMIT_CPU`` / ``RLIMIT_AS``。
       若需对未提供 ``executor`` 的调用路径打开默认资源限制，请通过
       ``default_max_cpu_seconds`` / ``default_max_memory_bytes`` 显式开启；
       已自行传入 ``executor`` 的调用方应自行配置其上限。
    """

    def __init__(
        self,
        session_manager: SessionManager | None = None,
        policy: CommandPolicy | None = None,
        executor: Executor | None = None,
        default_max_cpu_seconds: int | None = None,
        default_max_memory_bytes: int | None = None,
    ) -> None:
        self.session_manager = session_manager or SessionManager()
        self.policy = policy or CommandPolicy()
        if executor is None:
            executor = Executor(
                max_cpu_seconds=default_max_cpu_seconds,
                max_memory_bytes=default_max_memory_bytes,
            )
        self.executor = executor

    def create_session(self, owner: str | None = None) -> SandboxSession:
        return self.session_manager.create_session(owner=owner)

    def execute(self, request: SandboxRequest) -> SandboxResult:
        session = self.session_manager.get_session(request.session_id)
        # 策略校验：拦截要记一条 audit
        try:
            self.policy.validate(request, session)
        except SandboxError as exc:
            audit_log(
                "policy.reject",
                session_id=session.session_id,
                command=request.command,
                args=request.args,
                reason=type(exc).__name__,
                message=str(exc),
            )
            raise

        audit_log(
            "exec.start",
            session_id=session.session_id,
            command=request.command,
            args=request.args,
            timeout_ms=request.timeout_ms,
        )
        running_marked = False
        try:
            with self.session_manager.acquire_slot():
                # 槽位获取成功后再切到 running，避免饱和等待期间状态失真。
                self.session_manager.update_status(session.session_id, "running")
                running_marked = True
                result = self.executor.run(request, session)
        except Exception as exc:
            audit_log(
                "exec.error",
                session_id=session.session_id,
                error=type(exc).__name__,
                message=str(exc),
            )
            # 仅当已切到 running 才回退到 idle；否则保留原状态（如 created）。
            if running_marked:
                self.session_manager.update_status(session.session_id, "idle")
            raise

        self._accumulate_usage(session, result)
        self.session_manager.update_status(session.session_id, "idle")
        audit_log(
            "exec.end",
            session_id=session.session_id,
            success=result.success,
            exit_code=result.exit_code,
            timeout=result.timeout,
            duration_ms=result.duration_ms,
            cpu_time_ms=result.cpu_time_ms,
            memory_peak_bytes=result.memory_peak_bytes,
        )
        self._write_log(session, request, result)
        return result

    def cleanup_session(self, session_id: str) -> None:
        self.session_manager.cleanup_session(session_id)

    def write_workspace_file(self, session_id: str, relative_path: str, content: str) -> Path:
        session = self.session_manager.get_session(session_id)
        target = (session.workspace_dir / relative_path).resolve()
        workspace_root = session.workspace_dir.resolve()
        if target != workspace_root and workspace_root not in target.parents:
            raise ValueError(f"Path escapes workspace: {relative_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    @staticmethod
    def _accumulate_usage(session: SandboxSession, result: SandboxResult) -> None:
        u = session.resource_usage
        u["executions"] = u.get("executions", 0) + 1
        u["duration_ms"] = u.get("duration_ms", 0) + result.duration_ms
        if result.cpu_time_ms is not None:
            u["cpu_time_ms"] = u.get("cpu_time_ms", 0) + result.cpu_time_ms
        if result.memory_peak_bytes is not None:
            u["memory_peak_bytes"] = max(u.get("memory_peak_bytes", 0), result.memory_peak_bytes)

    def _write_log(self, session: SandboxSession, request: SandboxRequest, result: SandboxResult) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = session.logs_dir / f"{timestamp}.json"
        payload = {
            "session_id": session.session_id,
            "command": request.command,
            "args": request.args,
            "timeout_ms": request.timeout_ms,
            "result": asdict(result),
        }
        log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
