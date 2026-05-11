from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


# Session 状态机：created → running → idle/terminated
SessionStatus = Literal["created", "running", "idle", "terminated"]


@dataclass(slots=True)
class SandboxSession:
    session_id: str
    root_dir: Path
    workdir: Path
    logs_dir: Path
    # 元数据（带默认值，向后兼容）
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: SessionStatus = "created"
    owner: str | None = None
    # 累积资源使用：键如 "cpu_time_ms"/"memory_peak_bytes"/"executions"
    resource_usage: dict[str, int] = field(default_factory=dict)


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
    # 资源使用情况（None 表示当前平台不支持采样或未启用限制）。
    cpu_time_ms: int | None = None
    memory_peak_bytes: int | None = None
