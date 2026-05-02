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
        # 大小写归一化（Windows 下 C:\Windows 与 c:\windows 等价）
        norm = str(path)
        norm_cmp = norm.lower() if sys.platform == "win32" else norm
        for forbidden in self.forbidden_paths:
            f_cmp = forbidden.lower() if sys.platform == "win32" else forbidden
            if norm_cmp == f_cmp or norm_cmp.startswith(f_cmp.rstrip("/\\") + ("\\" if "\\" in f_cmp else "/")):
                raise PathForbiddenError(f"Path touches forbidden location: {path}")

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
