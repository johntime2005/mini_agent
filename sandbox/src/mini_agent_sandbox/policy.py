"""命令与源码策略层。

.. warning::
   ``CommandPolicy._validate_python_source`` 做的是 **AST 级静态扫描**，仅
   覆盖直接的 ``import`` / ``from ... import``。它**可被绕过**：

   * ``__import__("socket")``、``importlib.import_module("socket")``
   * ``exec("import socket")`` / ``eval(...)`` / 字符串拼接动态导入
   * 通过有副作用的第三方包间接触发禁用模块

   因此本层应被定位为 **defense-in-depth**，而非真正的安全边界。要做
   到对抗性隔离，请依赖 ``RLIMIT_*`` / ``seccomp`` / namespace / 容器 /
   独立 UID 等系统层机制。详见仓库根目录 ``SECURITY.md``。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from .errors import ArgumentNotAllowedError, CommandNotAllowedError, PathForbiddenError
from .types import SandboxRequest, SandboxSession

# 默认敏感路径黑名单（绝对路径前缀）。实际匹配时会做大小写归一化（Windows）。
_DEFAULT_FORBIDDEN_PATHS: tuple[str, ...] = (
    "/etc",
    "/root",
    "/var/log",
    "/proc",
    "/sys",
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
)

# 默认禁用的网络/危险模块（``import`` 顶级名一致时即拒绝）。
_DEFAULT_FORBIDDEN_MODULES: frozenset[str] = frozenset({
    "socket", "requests", "urllib", "urllib2", "urllib3",
    "http", "httpx", "ftplib", "telnetlib", "smtplib",
    "asyncio",  # 含 asyncio.open_connection；如需放开，显式用白名单
    "ctypes",   # 可调用系统 API
    "subprocess",
})


class CommandPolicy:
    def __init__(
        self,
        allowed_commands: set[str] | None = None,
        max_timeout_ms: int = 10000,
        forbidden_paths: tuple[str, ...] | None = None,
        forbidden_modules: frozenset[str] | None = None,
        module_allowlist: frozenset[str] | None = None,
    ) -> None:
        self.allowed_commands = allowed_commands or {"python"}
        self.max_timeout_ms = max_timeout_ms
        self.forbidden_paths = forbidden_paths if forbidden_paths is not None else _DEFAULT_FORBIDDEN_PATHS
        self.forbidden_modules = forbidden_modules if forbidden_modules is not None else _DEFAULT_FORBIDDEN_MODULES
        # 白名单优先：出现在白名单里的模块即使在黑名单里也放行。
        self.module_allowlist = module_allowlist or frozenset()

    def validate(self, request: SandboxRequest, session: SandboxSession) -> None:
        
        if request.command not in self.allowed_commands:
            raise CommandNotAllowedError(f"Command is not allowed: {request.command}")
        
        if request.timeout_ms <= 0 or request.timeout_ms > self.max_timeout_ms:
            raise ArgumentNotAllowedError(
                f"timeout_ms must be between 1 and {self.max_timeout_ms}, got {request.timeout_ms}"
            )
        if request.command == "python":
            self._validate_python_args(request.args, session.workspace_dir)
    # 检查python命令参数
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
        # 源码 AST 级静态审查（仅当脚本已存在时）
        if script_path.is_file():
            self._validate_python_source(script_path)

    def _resolve_workspace_path(self, workspace_dir: Path, relative_path: str) -> Path:
        candidate = (workspace_dir / relative_path).resolve()
        workspace_root = workspace_dir.resolve()
        if candidate != workspace_root and workspace_root not in candidate.parents:
            raise PathForbiddenError(f"Path escapes sandbox workspace: {relative_path}")
        self._check_forbidden_path(candidate)
        return candidate

    # ------------------------------------------------------------------
    # 新增：敏感路径与模块检查
    # ------------------------------------------------------------------
    def _check_forbidden_path(self, path: Path) -> None:
        """检查路径是否落入敏感目录前缀。

        使用 :py:meth:`pathlib.Path.is_relative_to` 做语义比较（Python 3.9+），
        避免手工 ``\\`` vs ``/`` 字符串前缀判断在分隔符混用场景下的歧义。
        Windows 下统一小写化做大小写不敏感比较；非当前平台的 forbidden
        条目（例如 Linux 进程上 ``C:\\Windows``）会被 ``Path`` 解析为不存
        在的相对路径，自然不命中。
        """
        candidate = self._normalize_for_compare(Path(path))
        for forbidden in self.forbidden_paths:
            forbidden_p = self._normalize_for_compare(Path(forbidden))
            try:
                if candidate.is_relative_to(forbidden_p):
                    raise PathForbiddenError(f"Path touches forbidden location: {path}")
            except ValueError:
                # is_relative_to 在 Python 3.9-3.11 上会抛 ValueError；3.12+ 改为返回 False。
                continue

    @staticmethod
    def _normalize_for_compare(p: Path) -> Path:
        """Windows 下做小写归一化（C:\\Windows ≡ c:\\windows）。其他平台原样。"""
        if sys.platform == "win32":
            return Path(str(p).lower())
        return p

    def _validate_python_source(self, script_path: Path) -> None:
        """AST 级扫描脚本中的 ``import``，拦截黑名单模块。"""
        try:
            source = script_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(script_path))
        except (OSError, SyntaxError):
            # 读不出来 / 语法错误交给运行期报错，不在策略层阻断。
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._assert_module_allowed(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root:
                    self._assert_module_allowed(root)

    def _assert_module_allowed(self, module_name: str) -> None:
        if module_name in self.module_allowlist:
            return
        if module_name in self.forbidden_modules:
            raise ArgumentNotAllowedError(
                f"Import of module '{module_name}' is not allowed by policy"
            )
