from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .executor import Executor
from .policy import CommandPolicy
from .session import SessionManager
from .types import SandboxRequest, SandboxResult, SandboxSession


class SandboxService:
    def __init__(
        self,
        session_manager: SessionManager | None = None,
        policy: CommandPolicy | None = None,
        executor: Executor | None = None,
    ) -> None:
        self.session_manager = session_manager or SessionManager()
        self.policy = policy or CommandPolicy()
        self.executor = executor or Executor()

    def create_session(self) -> SandboxSession:
        return self.session_manager.create_session()

    def execute(self, request: SandboxRequest) -> SandboxResult:
        session = self.session_manager.get_session(request.session_id)
        self.policy.validate(request, session)
        result = self.executor.run(request, session)
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
