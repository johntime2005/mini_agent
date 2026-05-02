"""沙箱审计日志。

统一提供 ``audit_log()`` 入口。使用标准 ``logging``，输出器 ``mini_agent_sandbox.audit``，
调用方可自行配置 handler / level / 重定向文件。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("mini_agent_sandbox.audit")


def audit_log(event: str, level: int = logging.INFO, **fields: Any) -> None:
    """输出一条结构化审计日志。

    ``event`` 是事件类型（如 ``exec.start``/``exec.end``/``policy.reject``），
    其余 kv 作为 ``extra`` 传给 logger，便于 JSON handler 提取。
    """
    logger.log(level, event, extra={"audit_event": event, "audit_fields": fields})
