from __future__ import annotations

import shutil
import subprocess
import sys
import time

from .types import SandboxRequest, SandboxResult, SandboxSession


class Executor:
    def __init__(self, max_output_bytes: int = 16384) -> None:
        self.max_output_bytes = max_output_bytes

    def run(self, request: SandboxRequest, session: SandboxSession) -> SandboxResult:
        started = time.perf_counter()
        executable = self._resolve_executable(request.command)
        process = subprocess.Popen(
            [executable, *request.args],
            cwd=session.workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=False,
        )
        timeout = False
        try:
            stdout, stderr = process.communicate(timeout=request.timeout_ms / 1000)
        except subprocess.TimeoutExpired:
            timeout = True
            process.kill()
            stdout, stderr = process.communicate()

        duration_ms = int((time.perf_counter() - started) * 1000)
        truncated = len(stdout) > self.max_output_bytes or len(stderr) > self.max_output_bytes
        return SandboxResult(
            success=(process.returncode == 0 and not timeout),
            exit_code=process.returncode,
            stdout=self._decode_output(stdout),
            stderr=self._decode_output(stderr),
            timeout=timeout,
            duration_ms=duration_ms,
            truncated=truncated,
        )

    def _decode_output(self, payload: bytes) -> str:
        limited = payload[: self.max_output_bytes]
        return limited.decode("utf-8", errors="replace")

    def _resolve_executable(self, command: str) -> str:
        if command in {"python", "python3"}:
            return sys.executable
        resolved = shutil.which(command)
        if resolved is None:
            raise FileNotFoundError(f"Executable not found: {command}")
        return resolved
