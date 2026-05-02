# 未来工作线路

## 后端层

### 改造成持续开发模型

- 给 Python 核心层补 pytest
- 给 gateway 补接口测试
- 优先覆盖：
  - src/mini_agent_sandbox/policy.py
  - src/mini_agent_sandbox/executor.py
  - src/mini_agent_sandbox/session.py

### 完善沙箱功能

- 增加 CPU / 内存 / 执行时长 / 并发限制
<!-- 改动文件：

types.py - SandboxResult 新增 cpu_time_ms、memory_peak_bytes（向后兼容）

executor.py - 重构为 BaseExecutor + LocalProcessExecutor，保留 Executor 别名

session.py - 新增并发限制（BoundedSemaphore + acquire_slot() + ConcurrencyLimitError）

tests/unit/test_executor_limits.py - 5个测试

tests/unit/test_session_concurrency.py - 4个测试 -->
- 增加 session 元数据与审计日志
<!-- | 文件 | 改动量 | 说明 |
|------|--------|------|
| types.py | +9行 | SandboxSession 新增4个字段（含默认值） |
| audit.py | 新建12行 | 唯一审计入口 audit_log(event, **fields) |
| session.py | +20行 | owner参数、_registry、update_status()、cleanup/create埋审计 |
| service.py | 改写 | 校验/执行/异常三处埋审计 + acquire_slot() + 累积 resource_usage |
| tests/unit/test_audit_m | 新建 | 4个测试用例 | -->

- 增加更严格的隔离策略
<!-- | 文件 | 改动量 | 说明 |
|------|--------|------|
| policy.py | 重写 | 增加 forbidden_paths / forbidden_modules / module_allowlist 配置 + 2个私有方法 |
| tests/unit/test_policy_isolation.py | 新建 | 5个测试用例 | -->
- 后续考虑容器级沙箱

### 添加多步迭代功能

- 增加 plan → execute → observe → retry 的多步循环
- 让工具调用标准化，而不是只做 prompt→代码→执行
- 给工具加结构化 schema
- 为 LLM tool calling / MCP 风格接口做准备

### 添加模型工作流（可选）

- 主模型用来控制是否拉起子模型进行代码生成，多个模型按照工作流运行
- 为聊天模型添加流式输出，若需运行代码则另行调用编码模型生成代码完成

### 插件系统和rpc方法（可选）

- 为二次开发提供平台
- 插件可在工具中注入更多方法供模型调用

### 适配器接入（可选）

- 使用onebot协议等接入qq
