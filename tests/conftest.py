"""
mini_agent_sandbox 测试的共享 fixture 定义。

"""

from __future__ import annotations

import pytest

from mini_agent_sandbox.service import SandboxService
from mini_agent_sandbox.session import SessionManager


@pytest.fixture
def session_manager(tmp_path):
    """构造一个把根目录钉在 pytest 临时目录下的 SessionManager。

    ``tmp_path`` 是 pytest 内建的函数级 fixture，每个测试用例会拿到一个
    全新的、用例结束后自动回收的目录。把 ``SessionManager.base_dir``
    指过去，就能保证：
    - 每个用例看到的都是干净的 ``sessions/`` 目录；
    - 用例之间 session_id 不会互相污染；
    - 不会碰真实的 /tmp/mini-agent-sandbox/。
    """
    return SessionManager(base_dir=tmp_path)


@pytest.fixture
def sandbox_session(session_manager):
    """直接创建一个可用的 SandboxSession，省掉用例里的 boilerplate。

   
    """
    return session_manager.create_session()


@pytest.fixture
def service(session_manager):
    """注入同一个临时 SessionManager 的 SandboxService。

    
    test_service.py 预留
    
   
    """
    return SandboxService(session_manager=session_manager)
