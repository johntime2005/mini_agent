"""SessionManager 的生命周期测试。

SessionManager 的职责：
  1. ``create_session()``：生成 ``sess_xxx`` 根目录 + ``workspace/`` +
     ``logs/``，并把这三者包进一个 ``SandboxSession`` dataclass 返回。
  2. ``get_session(id)``：按 id 拿回之前建过的 session；不存在就抛
     ``SessionNotFoundError``。
  3. ``cleanup_session(id)``：``shutil.rmtree`` 整个 session 根目录。

这三个操作合起来就是一条最小闭环："建 → 查 → 删（再查不到）"。
本文件的 4 个用例刚好把这条闭环连同一个"建两次不撞车"的健全性检查
全部盖住。

设计抉择：只依赖 conftest.py 里的 ``session_manager`` fixture
-------------------------------------------------------------
SessionManager 本来就吃一个 ``base_dir``，我们让 conftest 给它喂
``tmp_path`` 即可——不需要本地再造辅助函数。所有用例都靠 fixture 注入，

"""

from __future__ import annotations

import pytest

from mini_agent_sandbox.errors import SessionNotFoundError


def test_create_session_builds_workspace_and_logs(session_manager):
    """建完 session 之后，四件事应该同时成立：

    1. 返回的对象有一个以 ``sess_`` 开头的 ``session_id``；
    2. ``root_dir`` 真的就在 ``base_dir/sessions/<id>`` 下；
    3. ``workspace/`` 子目录真实存在；
    4. ``logs/`` 子目录真实存在。

    4条里每一条都对应 session.py 里的一行代码——任何一条回归都说明有
    人把 session 的目录结构改坏了。

    ``session_manager`` fixture 已经把 ``base_dir`` 指向了 tmp_path，
    所以这里不会污染真实文件系统。
    """
    session = session_manager.create_session()

    # 约定：sess_ 前缀是对外暴露的"版本兼容符"。改成别的前缀会影响
    # 日志正则 / gateway 里的字符串解析，所以这条断言要守住。
    assert session.session_id.startswith("sess_")

    # 根目录必须正好落在 base_dir/sessions/<id>——不能跑出去建到别处，
    # 否则 cleanup 时也会错。
    assert session.root_dir == session_manager.sessions_dir / session.session_id

    # workdir 和 logs 目录都应该真实存在（is_dir 顺带验证它是目录
    # 而不是意外被当成文件）。
    assert session.workdir.is_dir()
    assert session.logs_dir.is_dir()


def test_create_session_generates_unique_ids(session_manager):
    """连续 create 两次不能撞 id，也不能互相覆盖对方的目录。

    """
    first = session_manager.create_session()
    second = session_manager.create_session()

    assert first.session_id != second.session_id

    # 两个 root_dir 都应独立存在，且互不相同。
    assert first.root_dir != second.root_dir
    assert first.root_dir.is_dir()
    assert second.root_dir.is_dir()


def test_get_session_raises_when_missing(session_manager):
    """get_session 在 id 不存在时必须抛 SessionNotFoundError。


    这里用一个明显不合法的 id（``sess_does_not_exist_xxx``），避免
    和真实 id 凑巧撞上。
    """
    with pytest.raises(SessionNotFoundError):
        session_manager.get_session("sess_does_not_exist_xxx")


def test_cleanup_session_removes_directory(session_manager):
    """cleanup 之后两件事必须同时成立：

    1. 磁盘上的 session 根目录被删掉（shutil.rmtree 生效）；
    2. 再调用 get_session 会抛 SessionNotFoundError（语义闭环）。

    """
    session = session_manager.create_session()
    root_dir = session.root_dir
    assert root_dir.is_dir()  # 前置确认：建成功了

    session_manager.cleanup_session(session.session_id)

    assert not root_dir.exists()

    with pytest.raises(SessionNotFoundError):
        session_manager.get_session(session.session_id)
