from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .audit import audit_log
from .errors import SandboxError, SourceTamperedError
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

        # TOCTOU 防御：在 policy 校验后立即对源码取 hash 快照，
        # 等真正执行前再算一次，不一致则视为被篡改。这只是
        # defense-in-depth（无法完全防住 hash 与 exec 之间的 race），
        # 但可以挡住"先合法、后篡改"的最常见攻击形态。
        script_path, script_hash = self._snapshot_python_source(request, session)

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
                if script_hash is not None:
                    self._verify_python_source(script_path, script_hash)
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

    @staticmethod
    def _snapshot_python_source(
        request: SandboxRequest, session: SandboxSession
    ) -> tuple[Path | None, str | None]:
        """对将要执行的 .py 文件取 SHA-256 快照。仅在能定位到工作区
        内的可读文件时返回 (path, hex_digest)；否则 (None, None)。
        """
        if request.command not in {"python", "python3"}:
            return None, None
        if not request.args or request.args[0].startswith("-"):
            return None, None
        candidate = (session.workspace_dir / request.args[0]).resolve()
        try:
            candidate.relative_to(session.workspace_dir.resolve())
        except ValueError:
            return None, None
        if not candidate.is_file():
            return None, None
        try:
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        except OSError:
            return None, None
        return candidate, digest

    @staticmethod
    def _verify_python_source(script_path: Path | None, expected_hash: str) -> None:
        """与 _snapshot_python_source 取到的 hash 比对，不一致抛 SourceTamperedError。"""
        if script_path is None:
            return
        try:
            current = hashlib.sha256(script_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise SourceTamperedError(
                f"Failed to re-read script for TOCTOU verification: {script_path}"
            ) from exc
        if current != expected_hash:
            raise SourceTamperedError(
                f"Script content changed between policy validation and execution: {script_path}"
            )

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
