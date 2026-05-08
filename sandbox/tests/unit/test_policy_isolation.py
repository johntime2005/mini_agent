"""隔离策略测试：敏感路径 & 网络/危险模块拦截。

覆盖目标 3 的 4 个关键分支：

1. 脚本路径指向敏感系统目录（构造超出 workspace 的路径也会先被
   路径穿越规则拦下，所以这里我们直接给 policy 喂一个"伪装的
   workspace"，让敏感路径命中）。
2. 脚本源码里 ``import socket`` → 拒绝。
3. 脚本源码里 ``from requests import get`` → 拒绝。
4. 白名单覆盖黑名单：显式放行 ``socket`` 后同样的脚本必须通过。
"""

from __future__ import annotations

import pytest

from mini_agent_sandbox.errors import ArgumentNotAllowedError, PathForbiddenError
from mini_agent_sandbox.policy import CommandPolicy
from mini_agent_sandbox.types import SandboxRequest


def _req(sandbox_session, args, timeout_ms: int = 1000) -> SandboxRequest:
    return SandboxRequest(
        session_id=sandbox_session.session_id,
        command="python",
        args=args,
        timeout_ms=timeout_ms,
    )


# ---------------------------------------------------------------------------
# 敏感路径
# ---------------------------------------------------------------------------
def test_policy_rejects_forbidden_workspace_root(sandbox_session, tmp_path):
    """workspace_dir 落在敏感路径前缀下时，``validate_workspace`` 必须拒绝。

    自 PR3 评审 #8 起，敏感路径检查从 ``_resolve_workspace_path`` 上移到
    ``CommandPolicy.validate_workspace``，由 ``SandboxService.create_session``
    在创建会话后立即调用一次，避免每个 candidate 重复检查。
    """
    # 把 forbidden_paths 临时指向 tmp_path，模拟"workspace 落在敏感区"。
    policy = CommandPolicy(forbidden_paths=(str(tmp_path),))

    with pytest.raises(PathForbiddenError):
        policy.validate_workspace(sandbox_session.workspace_dir)


# ---------------------------------------------------------------------------
# 网络/危险模块
# ---------------------------------------------------------------------------
def test_policy_rejects_network_import(sandbox_session):
    (sandbox_session.workspace_dir / "net.py").write_text(
        "import socket\nprint('x')\n", encoding="utf-8"
    )
    policy = CommandPolicy()
    with pytest.raises(ArgumentNotAllowedError):
        policy.validate(_req(sandbox_session, ["net.py"]), sandbox_session)


def test_policy_rejects_from_import_of_forbidden_module(sandbox_session):
    (sandbox_session.workspace_dir / "r.py").write_text(
        "from requests import get\n", encoding="utf-8"
    )
    policy = CommandPolicy()
    with pytest.raises(ArgumentNotAllowedError):
        policy.validate(_req(sandbox_session, ["r.py"]), sandbox_session)


def test_policy_allowlist_overrides_forbidden(sandbox_session):
    """白名单里放行的模块即便在黑名单里也应通过。"""
    (sandbox_session.workspace_dir / "net.py").write_text(
        "import socket\n", encoding="utf-8"
    )
    policy = CommandPolicy(module_allowlist=frozenset({"socket"}))
    # 不抛异常即为通过
    policy.validate(_req(sandbox_session, ["net.py"]), sandbox_session)


def test_policy_accepts_benign_imports(sandbox_session):
    """不在黑名单里的模块（如 json）应正常通过。"""
    (sandbox_session.workspace_dir / "ok.py").write_text(
        "import json\nprint(json.dumps({'x': 1}))\n", encoding="utf-8"
    )
    policy = CommandPolicy()
    policy.validate(_req(sandbox_session, ["ok.py"]), sandbox_session)
