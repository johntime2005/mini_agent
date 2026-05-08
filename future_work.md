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
- 增加 session 元数据与审计日志
- 增加更严格的隔离策略
- 后续考虑容器级沙箱（DockerExecutor / FirecrackerExecutor / gVisor —
  `BaseExecutor` 抽象已为此预留扩展点；安全边界详见 `sandbox/SECURITY.md`）
- seccomp / Linux namespaces / cgroup v2 真隔离
- TOCTOU 加固：使用 `pass_fds=[fd]` + `/dev/fd/{fd}` 让校验与执行
  共用同一 inode（当前 service 层只做 SHA-256 重校验）

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
