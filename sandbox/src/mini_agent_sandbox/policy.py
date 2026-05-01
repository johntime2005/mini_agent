from __future__ import annotations

from pathlib import Path

from .errors import ArgumentNotAllowedError, CommandNotAllowedError, PathForbiddenError
from .types import SandboxRequest, SandboxSession


class CommandPolicy:
    def __init__(self, allowed_commands: set[str] | None = None, max_timeout_ms: int = 10000) -> None:
        self.allowed_commands = allowed_commands or {"python"}
        self.max_timeout_ms = max_timeout_ms

    def validate(self, request: SandboxRequest, session: SandboxSession) -> None:
        if request.command not in self.allowed_commands:
            raise CommandNotAllowedError(f"Command is not allowed: {request.command}")
        if request.timeout_ms <= 0 or request.timeout_ms > self.max_timeout_ms:
            raise ArgumentNotAllowedError(
                f"timeout_ms must be between 1 and {self.max_timeout_ms}, got {request.timeout_ms}"
            )
        if request.command == "python":
            self._validate_python_args(request.args, session.workspace_dir)

    def _validate_python_args(self, args: list[str], workspace_dir: Path) -> None:
        if not args:
            raise ArgumentNotAllowedError("python requires a target .py file inside the sandbox workspace")
        script_arg = args[0]
        if script_arg.startswith("-"):
            raise ArgumentNotAllowedError("python flags such as -c or -m are not allowed in this sandbox")
        script_path = self._resolve_workspace_path(workspace_dir, script_arg)
        if script_path.suffix != ".py":
            raise ArgumentNotAllowedError("Only .py files may be executed")
        for extra_arg in args[1:]:
            if "\x00" in extra_arg:
                raise ArgumentNotAllowedError("Null bytes are not allowed in arguments")

    def _resolve_workspace_path(self, workspace_dir: Path, relative_path: str) -> Path:
        candidate = (workspace_dir / relative_path).resolve()
        workspace_root = workspace_dir.resolve()
        if candidate != workspace_root and workspace_root not in candidate.parents:
            raise PathForbiddenError(f"Path escapes sandbox workspace: {relative_path}")
        return candidate
