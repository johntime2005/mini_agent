"""Executor 行为测试。

覆盖 3 个我们在别处都默认"它一定会这样"的属性：

1. **成功路径**：跑一个普通的 ``print(...)``，能拿到 stdout，exit_code=0。
2. **超时路径**：死循环脚本 + 500ms 超时，必须杀掉进程并把 ``timeout``
   标志置 True。
3. **截断路径**：大到爆炸的 stdout 必须在 ``max_output_bytes`` 处被截断，
   ``truncated`` 标志置 True。

fixture 使用约定
----------------
我们用的是 conftest.py 里的 ``sandbox_session``，它已经挂在 tmp_path
下——所以写 ``hello.py`` / ``loop.py`` / ``big.py`` 这些临时脚本不
会污染真实 /tmp。
"""

from __future__ import annotations

from mini_agent_sandbox.executor import Executor
from mini_agent_sandbox.types import SandboxRequest


def _write(sandbox_session, name: str, content: str) -> None:
    """把一段 Python 源代码写进当前 sandbox workspace。

    """
    (sandbox_session.workdir / name).write_text(content, encoding="utf-8")


def _request(sandbox_session, script: str, *, timeout_ms: int = 5000) -> SandboxRequest:
    """构造一个执行请求。默认超时 5 秒，足够让 Python 解释器启动完成。

    注意：虽然 ``CommandPolicy.max_timeout_ms`` 默认是 10000，这里我
    们不受它影响——这是 Executor 的单元测试，直接跳过 policy 层。
    policy 相关的测试在 test_policy.py。
    """
    return SandboxRequest(
        session_id=sandbox_session.session_id,
        command="python",
        args=[script],
        timeout_ms=timeout_ms,
    )


def test_executor_runs_python_successfully(sandbox_session):
    """成功路径：一个最简单的 print 脚本必须能跑通并把 stdout 带回来。

    验证 5 条断言：
        1. success=True          —— 综合判断（returncode==0 且未超时）
        2. exit_code=0           —— 底层进程退出码
        3. timeout=False         —— 没有触发超时分支
        4. 'hi from test' in stdout —— print 出的内容被正确捕获和解码
        5. stderr == ''          —— 没有意外的错误输出

    这 5 条断言是"成功语义"的 AND，任何一条失败都说明 Executor 的
    快乐路径挂了。
    """
    _write(sandbox_session, "hello.py", "print('hi from test')\n")
    executor = Executor()

    result = executor.run(_request(sandbox_session, "hello.py"), sandbox_session)

    assert result.success is True
    assert result.exit_code == 0
    assert result.timeout is False
    assert "hi from test" in result.stdout
    assert result.stderr == ""


def test_executor_reports_timeout(sandbox_session):
    """超时路径：死循环脚本 + 500ms 超时，必须报告 timeout=True 且 success=False。

    """
    # Busy loop；执行到 timeout_ms 后必须被 Executor kill 掉。
    _write(sandbox_session, "loop.py", "while True:\n    pass\n")
    executor = Executor()

    result = executor.run(_request(sandbox_session, "loop.py", timeout_ms=500), sandbox_session)

    assert result.timeout is True
    assert result.success is False


def test_executor_truncates_large_stdout(sandbox_session):
    """截断路径：10 万字节 stdout + max_output_bytes=512，必须截到 512 且置 truncated=True。

    """
    _write(sandbox_session, "big.py", "import sys\nsys.stdout.write('A' * 100000)\n")
    executor = Executor(max_output_bytes=512)

    result = executor.run(_request(sandbox_session, "big.py"), sandbox_session)

    assert result.truncated is True
    # _decode_output 先按 max_output_bytes 切字节再解码，所以
    # 结果字符串的长度不可能超过字节预算。
    assert len(result.stdout) <= 512
