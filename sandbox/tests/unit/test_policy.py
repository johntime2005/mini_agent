"""CommandPolicy 的拒绝路径 / 接受路径测试。

我们覆盖的 5 个关键分支，对应 ``policy.py`` 里 5 条决策：

| # | 分支                               | 对应源码位置                               | 风险                                   |
|---|------------------------------------|--------------------------------------------|----------------------------------------|
| 1 | 命令不在白名单                     | ``if request.command not in ...``          | 任意命令执行                           |
| 2 | python flag（``-c`` / ``-m``）    | ``if script_arg.startswith("-")``          | 绕过 ".py 必须在 workspace 内" 的限制 |
| 3 | 非 .py 后缀                        | ``if script_path.suffix != ".py"``         | 把 shell 脚本/二进制当 python 启动    |
| 4 | 路径穿越（``../../etc/passwd.py``）| ``_resolve_workspace_path`` 的 parents 检查 | 读/写 workspace 之外的文件             |
| 5 | 合法 python 请求（快乐路径）        | 整条链路通过                               | 避免误杀正常请求                       |


这里还**没**测的东西（留到后面补）：
- ``timeout_ms`` 的边界（0、负、大于上限）
- 参数里含 ``\\x00``
- workspace 内嵌套子目录脚本

这些都不是"会被恶意利用"的主路径，先锁 5 条最重要的。
"""

from __future__ import annotations

import pytest

from mini_agent_sandbox.errors import (
    ArgumentNotAllowedError,
    CommandNotAllowedError,
    PathForbiddenError,
)
from mini_agent_sandbox.policy import CommandPolicy
from mini_agent_sandbox.types import SandboxRequest


def _request(sandbox_session, *, command: str = "python", args=None, timeout_ms: int = 1000):
    """构造一个用来喂给 policy.validate 的 SandboxRequest。


    参数说明：
        - ``sandbox_session``：来自 conftest.py 的 fixture，提供了一个真实
            存在的 workdir，policy 里的路径解析需要它。
    - ``command``：被测命令，默认 ``python``（白名单命令）。
    - ``args``：脚本参数列表；不传时默认 ``["hello.py"]``（合法参数）。
    - ``timeout_ms``：用默认上限内的 1000ms，避免误触发 timeout 分支。
    """
    return SandboxRequest(
        session_id=sandbox_session.session_id,
        command=command,
        args=list(args) if args is not None else ["hello.py"],
        timeout_ms=timeout_ms,
    )


def test_policy_rejects_command_outside_whitelist(sandbox_session):
    """非白名单命令（例：bash）必须被 CommandNotAllowedError 拦下。

   
    """
    policy = CommandPolicy()

    with pytest.raises(CommandNotAllowedError):
        policy.validate(_request(sandbox_session, command="bash"), sandbox_session)


def test_policy_rejects_python_flags(sandbox_session):
    """以 ``-`` 开头的参数（例：-c 'print(1)'）必须被拒。

    
    """
    policy = CommandPolicy()

    with pytest.raises(ArgumentNotAllowedError):
        policy.validate(_request(sandbox_session, args=["-c", "print(1)"]), sandbox_session)


def test_policy_rejects_non_py_extension(sandbox_session):
    """只允许执行 .py 文件；.txt / .sh / 无后缀都要被拒。

    这条约束看似鸡肋（反正 python 解释器也不会真去执行 .txt），但它的
    真正价值是"保底"：
        - 如果有人把 policy 的其它分支改坏了，这条至少还能挡掉一部分
          误用；
        - 它也让用户写出的错误更友好（一看报错就知道文件名写错了）。
    """
    policy = CommandPolicy()

    with pytest.raises(ArgumentNotAllowedError):
        policy.validate(_request(sandbox_session, args=["hello.txt"]), sandbox_session)


def test_policy_rejects_path_traversal(sandbox_session):
    """``../../etc/passwd.py`` 这种路径穿越必须被 PathForbiddenError 拦下。

    注意后缀仍然是 ``.py``——这是故意的：它证明 **policy 的路径检查独立
    于后缀检查**，即使伪装成 .py 文件，只要解析后的绝对路径跳出了
    workspace，就必须拒绝。
    """
    policy = CommandPolicy()

    with pytest.raises(PathForbiddenError):
        policy.validate(_request(sandbox_session, args=["../../etc/passwd.py"]), sandbox_session)


def test_policy_accepts_valid_python_request(sandbox_session):
    """快乐路径：合法的 ``python hello.py mini-agent`` 必须顺利通过。

    """
    policy = CommandPolicy()

    # 成功标志：下面这行**没有**抛异常。pytest 不需要显式 assert，
   
    policy.validate(_request(sandbox_session, args=["hello.py", "mini-agent"]), sandbox_session)
