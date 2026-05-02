"""Executor 子系统。

本模块提供一个抽象基类 :class:`BaseExecutor` 和一个本地进程实现
:class:`LocalProcessExecutor`（同时保留 :class:`Executor` 别名以保持
向后兼容）。未来可平滑接入 ``DockerExecutor`` 等远端/容器化实现。

主要扩展点（相对于最初版本）：

1. **执行时长**：沿用 ``subprocess.communicate(timeout=...)``。
2. **CPU / 内存限制**：通过 ``resource.setrlimit`` 在子进程启动前设置；
   Windows 下无 ``resource`` 模块，降级为仅记录警告。
3. **资源使用采样**：Unix 下从 ``os.wait4`` 读取 ``rusage``；Windows
   下如安装了 ``psutil`` 亦会尝试采样，否则字段为 ``None``。
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from abc import ABC, abstractmethod

from .types import SandboxRequest, SandboxResult, SandboxSession

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 平台检测：Windows 上 ``resource`` 模块不可用，降级为"仅记录警告"。
# ---------------------------------------------------------------------------
HAS_RESOURCE = sys.platform != "win32"
if HAS_RESOURCE:
    import resource  # type: ignore[import-not-found]
else:  # pragma: no cover - Windows-only path
    resource = None  # type: ignore[assignment]


class BaseExecutor(ABC):
    """所有 Executor 实现的抽象基类。

    为将来的 ``DockerExecutor`` / ``RemoteExecutor`` 等实现保留统一入口。
    """

    @abstractmethod
    def run(self, request: SandboxRequest, session: SandboxSession) -> SandboxResult:
        """执行一条沙箱请求并返回结果。"""


class LocalProcessExecutor(BaseExecutor):
    """基于 ``subprocess`` 的本地进程执行器。"""

    def __init__(
        self,
        max_output_bytes: int = 16384,
        max_cpu_seconds: int | None = None,
        max_memory_bytes: int | None = None,
    ) -> None:
        self.max_output_bytes = max_output_bytes
        self.max_cpu_seconds = max_cpu_seconds
        self.max_memory_bytes = max_memory_bytes

        if not HAS_RESOURCE and (max_cpu_seconds is not None or max_memory_bytes is not None):
            # Windows 下无法强制限制；仅记录警告，保证功能可用。
            logger.warning(
                "Resource limits (cpu=%s, mem=%s) requested but 'resource' module "
                "is unavailable on this platform; limits will NOT be enforced.",
                max_cpu_seconds,
                max_memory_bytes,
            )

    # ------------------------------------------------------------------
    # 公开入口
    # ------------------------------------------------------------------
    def run(self, request: SandboxRequest, session: SandboxSession) -> SandboxResult:
        started = time.perf_counter()
        executable = self._resolve_executable(request.command)

        # Force UTF-8 in the child process so that non-ASCII stdout/stderr
        # (e.g. Chinese) is not mangled on Windows where the default codepage
        # is gbk/cp936. Both env var and -X utf8 flag are set defensively.
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"

        run_args: list[str] = [executable]
        if request.command in {"python", "python3"}:
            run_args.extend(["-X", "utf8"])
        run_args.extend(request.args)

        popen_kwargs: dict = dict(
            cwd=session.workspace_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=False,
            env=child_env,
        )
        # preexec_fn 仅在 Unix 上可用；Windows 下必须省略。
        if HAS_RESOURCE:
            popen_kwargs["preexec_fn"] = self._build_preexec_fn()

        process = subprocess.Popen(run_args, **popen_kwargs)

        timeout = False
        try:
            stdout, stderr = process.communicate(timeout=request.timeout_ms / 1000)
        except subprocess.TimeoutExpired:
            timeout = True
            process.kill()
            stdout, stderr = process.communicate()

        duration_ms = int((time.perf_counter() - started) * 1000)
        truncated = len(stdout) > self.max_output_bytes or len(stderr) > self.max_output_bytes

        cpu_time_ms, memory_peak_bytes = self._sample_resource_usage()

        return SandboxResult(
            success=(process.returncode == 0 and not timeout),
            exit_code=process.returncode,
            stdout=self._decode_output(stdout),
            stderr=self._decode_output(stderr),
            timeout=timeout,
            duration_ms=duration_ms,
            truncated=truncated,
            cpu_time_ms=cpu_time_ms,
            memory_peak_bytes=memory_peak_bytes,
        )

    # ------------------------------------------------------------------
    # 私有辅助
    # ------------------------------------------------------------------
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

    def _build_preexec_fn(self):
        """构造在子进程 fork 之后、exec 之前执行的钩子。

        只有传了 ``max_cpu_seconds`` 或 ``max_memory_bytes`` 时才会真正
        调用 ``resource.setrlimit``，避免无意义开销。
        """
        max_cpu = self.max_cpu_seconds
        max_mem = self.max_memory_bytes
        if max_cpu is None and max_mem is None:
            return None

        def _apply_limits() -> None:  # pragma: no cover - runs in child proc
            if max_cpu is not None:
                resource.setrlimit(resource.RLIMIT_CPU, (max_cpu, max_cpu))
            if max_mem is not None:
                resource.setrlimit(resource.RLIMIT_AS, (max_mem, max_mem))

        return _apply_limits

    def _sample_resource_usage(self) -> tuple[int | None, int | None]:
        """采样子进程的 CPU 时间（毫秒）与峰值内存（字节）。

        - Unix：通过 ``resource.getrusage(RUSAGE_CHILDREN)`` 读取；注意
          ``ru_maxrss`` 单位在 Linux 上是 KiB、在 macOS 上是字节，这里
          统一归一化为字节。
        - Windows：无 ``resource`` 模块时返回 ``(None, None)``。
        """
        if not HAS_RESOURCE:
            return None, None
        try:
            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        except Exception:  # pragma: no cover - defensive
            return None, None

        cpu_time_ms = int((usage.ru_utime + usage.ru_stime) * 1000)
        # Linux: KiB; macOS (Darwin): bytes. 统一归一化为字节。
        if sys.platform == "darwin":
            memory_peak_bytes = int(usage.ru_maxrss)
        else:
            memory_peak_bytes = int(usage.ru_maxrss) * 1024
        return cpu_time_ms, memory_peak_bytes


# ---------------------------------------------------------------------------
# 向后兼容别名：原 Executor 类名仍可用，等价于 LocalProcessExecutor。
# ---------------------------------------------------------------------------
Executor = LocalProcessExecutor
