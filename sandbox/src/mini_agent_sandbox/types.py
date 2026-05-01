from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SandboxSession:
    session_id: str
    root_dir: Path
    workspace_dir: Path
    logs_dir: Path


@dataclass(slots=True)
class SandboxRequest:
    session_id: str
    command: str
    args: list[str]
    timeout_ms: int = 5000


@dataclass(slots=True)
class SandboxResult:
    success: bool
    exit_code: int | None
    stdout: str
    stderr: str
    timeout: bool
    duration_ms: int
    truncated: bool
