from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from .errors import SessionNotFoundError
from .types import SandboxSession


class SessionManager:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path("/tmp/mini-agent-sandbox")
        self.sessions_dir = self.base_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> SandboxSession:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session_root = self.sessions_dir / session_id
        workspace_dir = session_root / "workspace"
        logs_dir = session_root / "logs"
        workspace_dir.mkdir(parents=True, exist_ok=False)
        logs_dir.mkdir(parents=True, exist_ok=False)
        return SandboxSession(
            session_id=session_id,
            root_dir=session_root,
            workspace_dir=workspace_dir,
            logs_dir=logs_dir,
        )

    def get_session(self, session_id: str) -> SandboxSession:
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
