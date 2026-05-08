"""Executor 子系统。

本模块提供一个抽象基类 :class:`BaseExecutor` 和一个本地进程实现
:class:`LocalProcessExecutor`（同时保留 :class:`Executor` 别名以保持
向后兼容）。未来可平滑接入 ``DockerExecutor`` 等远端/容器化实现。

主要扩展点（相对于最初版本）：

1. **执行时长**：Unix 下用 ``os.wait4 + WNOHANG`` 自轮询，超时触发
   ``os.killpg`` 杀整个进程组；Windows 下退化为 ``communicate(timeout=...)``。
2. **CPU / 内存限制**：通过 ``resource.setrlimit`` 在子进程启动前设置；
   Windows 下无 ``resource`` 模块，降级为仅记录警告。
3. **资源使用采样**：Unix 下 ``os.wait4`` 直接返回**这一个**子进程的
   ``rusage``，避免 ``RUSAGE_CHILDREN`` 累计 bug；Windows 下字段为 ``None``。
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
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

    # 轮询子进程退出状态的间隔（秒）。20ms 在 CPU 占用与超时精度间取折中。
    _POLL_INTERVAL_S = 0.02

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
        # Unix：fork 出新 session，便于超时时一键 ``killpg`` 整组。
        # 同时通过 ``preexec_fn`` 在 exec 前调用 ``setrlimit``。
        if HAS_RESOURCE:
            popen_kwargs["start_new_session"] = True
            popen_kwargs["preexec_fn"] = self._build_preexec_fn()

        process = subprocess.Popen(run_args, **popen_kwargs)

        if HAS_RESOURCE:
            stdout, stderr, timeout, cpu_time_ms, memory_peak_bytes = self._wait_unix(
                process, request.timeout_ms / 1000
            )
        else:
            stdout, stderr, timeout = self._wait_windows(process, request.timeout_ms / 1000)
            cpu_time_ms = None
            memory_peak_bytes = None

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
            cpu_time_ms=cpu_time_ms,
            memory_peak_bytes=memory_peak_bytes,
        )

    # ------------------------------------------------------------------
    # 平台分支：Unix 用 wait4，Windows 退化到 communicate
    # ------------------------------------------------------------------
    def _wait_unix(
        self, process: subprocess.Popen, timeout_s: float
    ) -> tuple[bytes, bytes, bool, int | None, int | None]:
        """Unix 路径：``os.wait4`` 拿 per-process rusage，超时 ``killpg``。

        - 用两个 daemon 线程异步排空 stdout/stderr 管道，避免管道满导致子进程阻塞。
        - 主线程循环 ``os.wait4(pid, WNOHANG)`` 并比对 deadline。
        - 超时分支：``os.killpg(pgid, SIGKILL)`` 收掉整个进程组（含子进程
          自己 fork 出的孙进程），然后阻塞 ``wait4`` 收尸。
        """
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []

        def _drain(stream, sink: list[bytes]) -> None:
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    sink.append(chunk)
            finally:
                stream.close()

        t_out = threading.Thread(target=_drain, args=(process.stdout, stdout_chunks), daemon=True)
        t_err = threading.Thread(target=_drain, args=(process.stderr, stderr_chunks), daemon=True)
        t_out.start()
        t_err.start()

        deadline = time.monotonic() + timeout_s
        timeout = False
        rusage = None

        while True:
            try:
                pid_r, status, ru = os.wait4(process.pid, os.WNOHANG)
            except ChildProcessError:
                # 已被其他途径 reap（例外路径）。
                pid_r, status, ru = process.pid, 0, None
                break
            if pid_r != 0:
                rusage = ru
                process.returncode = self._exit_code_from_status(status)
                break
            if time.monotonic() > deadline:
                timeout = True
                self._kill_process_group(process.pid)
                try:
                    _, status, rusage = os.wait4(process.pid, 0)
                    process.returncode = self._exit_code_from_status(status)
                except ChildProcessError:  # pragma: no cover - defensive
                    process.returncode = -signal.SIGKILL
                break
            time.sleep(self._POLL_INTERVAL_S)

        # 排空 IO 线程。子进程已退出 → 管道一定 EOF，read 立即返回。
        t_out.join(timeout=1.0)
        t_err.join(timeout=1.0)

        cpu_time_ms: int | None
        memory_peak_bytes: int | None
        if rusage is None:
            cpu_time_ms = None
            memory_peak_bytes = None
        else:
            cpu_time_ms = int((rusage.ru_utime + rusage.ru_stime) * 1000)
            # Linux: KiB; macOS (Darwin): bytes. 统一归一化为字节。
            if sys.platform == "darwin":
                memory_peak_bytes = int(rusage.ru_maxrss)
            else:
                memory_peak_bytes = int(rusage.ru_maxrss) * 1024

        return b"".join(stdout_chunks), b"".join(stderr_chunks), timeout, cpu_time_ms, memory_peak_bytes

    def _wait_windows(
        self, process: subprocess.Popen, timeout_s: float
    ) -> tuple[bytes, bytes, bool]:  # pragma: no cover - Windows-only path
        """Windows 路径：沿用 ``communicate(timeout=...)``，无 rusage 采样。"""
        timeout = False
        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timeout = True
            process.kill()
            stdout, stderr = process.communicate()
        return stdout, stderr, timeout

    @staticmethod
    def _kill_process_group(pid: int) -> None:
        """SIGKILL 整个进程组；找不到则当作已退出。"""
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            return
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:  # pragma: no cover - race
            return

    @staticmethod
    def _exit_code_from_status(status: int) -> int:
        """把 ``os.wait4`` 返回的 status 转成 ``Popen.returncode`` 风格。"""
        # Python 3.9+ 提供 ``os.waitstatus_to_exitcode``，被信号终止时返回负值。
        return os.waitstatus_to_exitcode(status)

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


# ---------------------------------------------------------------------------
# 向后兼容别名：原 Executor 类名仍可用，等价于 LocalProcessExecutor。
# ---------------------------------------------------------------------------
Executor = LocalProcessExecutor
