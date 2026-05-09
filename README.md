# mini-agent sandbox

一个最小可运行的 Python 命令沙盒原型，面向课程项目场景。

现在同时包含一个**最小 Node.js / Express 网关**，用于：

- 调用大模型生成 Python 代码
- 通过现有 Python sandbox CLI 写入 session workspace
- 触发沙盒执行并返回执行结果

## 能力范围

- 独立 session 工作目录
- 仅允许执行 `python`
- 仅允许执行 sandbox workspace 内的 `.py` 文件
- 超时控制
- 输出截断
- JSON 执行日志
- Express HTTP 网关
- 大模型生成代码后自动执行

## 快速开始

本仓库使用 [uv](https://docs.astral.sh/uv/) 作为统一的 Python 包/环境管理器，
仓库根目录是一个 **uv workspace**，成员包括 `sandbox/`、`api/`。

```bash
# 一次性安装所有 workspace 成员（sandbox + api）到 .venv
uv sync

# 运行 sandbox demo
uv run sandbox-demo demo
```

如果只想安装 sandbox 子包：

```bash
uv sync --package mini-agent-sandbox
```

## 手动运行

## Python 可调用工具示范

除了 CLI，这个项目现在也提供了一个最小 **Python 可调用工具包装**，直接复用
`SandboxService`：

```python
from mini_agent_sandbox import run_python_tool

result = run_python_tool(
    "print('hello from callable tool')",
    script_path="hello.py",
)

print(result["result"]["stdout"])
```

还附带了一个更贴近“工具调用”的示范：

```python
from mini_agent_sandbox import word_count_tool

result = word_count_tool("the sandbox can be wrapped as a callable tool")
print(result["parsed_output"])
```

直接运行完整示例：

```bash
uv run python examples/python_callable_tool_demo.py
```

### 1. 创建 session

```bash
uv run sandbox-demo create-session
```

记录输出中的 `session_id` 和 `workspace_dir`。

### 2. 在 workspace 中写入脚本

例如在 `workspace_dir` 下写一个 `main.py`。

### 3. 执行脚本

```bash
uv run sandbox-demo run <session_id> main.py arg1 arg2
```

### 4. 写入文件

```bash
printf 'print("hello")\n' | uv run sandbox-demo write-file <session_id> hello.py --stdin
```

### 5. 清理 session

```bash
uv run sandbox-demo cleanup-session <session_id>
```

## Node.js / Express 网关

网关代码位于 `gateway/`，职责是：

1. 接收 HTTP 请求
2. 调用大模型生成 Python 代码
3. 调用 Python CLI 创建 sandbox session / 写文件 / 执行脚本
4. 把执行结果回传给调用方

### 前置要求

- [uv](https://docs.astral.sh/uv/) 0.5+（统一管理 Python 与依赖）
- Python 3.11+（uv 会按需自动下载）
- Bun 1.0+
- 已完成 workspace 同步：`uv sync`
- 可用的大模型兼容接口（默认按 OpenAI Chat Completions 协议调用）

### 安装网关依赖

```bash
cd gateway
bun install
```

### 环境变量

最小需要：

```bash
export LLM_API_KEY=your_api_key
```

可选变量：

```bash
export PORT=3000
export PYTHON_BIN=python
export SANDBOX_MODULE=mini_agent_sandbox.cli
export LLM_API_URL=https://api.openai.com/v1/chat/completions
export LLM_MODEL=gpt-4o-mini
export DEFAULT_TIMEOUT_MS=5000
export MAX_TIMEOUT_MS=10000
export SESSION_TTL_MS=600000
export CONTEXT_HISTORY_LIMIT=10
export MAX_CONTEXT_PREVIEW_LENGTH=4000
```

### 配置文件持久化（推荐）

现在网关也支持把 LLM 配置持久化到配置文件，默认路径：

```bash
.mini-agent/gateway-config.json
```

也可以通过环境变量覆盖路径：

```bash
export GATEWAY_CONFIG_PATH=/your/path/gateway-config.json
```

配置文件示例：

```json
{
  "llmApiKey": "your_api_key",
  "llmApiUrl": "https://api.openai.com/v1/chat/completions",
  "llmModel": "gpt-4o-mini"
}
```

优先级：**配置文件 > 环境变量 > 内置默认值**。

你也可以通过 HTTP 接口写入持久化配置：

```bash
curl -X PUT http://localhost:3000/config/llm \
  -H 'Content-Type: application/json' \
  -d '{
    "llmApiKey": "your_api_key",
    "llmApiUrl": "https://api.openai.com/v1/chat/completions",
    "llmModel": "gpt-4o-mini"
  }'
```

### 最近上下文缓存

网关现在会缓存最近 `N` 条上下文，并在后续 `/generate-and-run` 调用大模型时自动注入这些上下文。

缓存内容包括：

- 用户指令
- 实际执行的命令
- 命令执行返回（stdout / stderr / exit code 等）

默认最近条数来自：

```bash
export CONTEXT_HISTORY_LIMIT=10
```

单条缓存内容会做截断，默认长度：

```bash
export MAX_CONTEXT_PREVIEW_LENGTH=4000
```

这些上下文会持久化写入 `GATEWAY_CONFIG_PATH` 指向的 JSON 文件中的 `contextHistory` 字段。

现在上下文缓存按 **sessionId 隔离**：

- 只会把**同一个 sessionId** 的历史上下文注入给模型
- 不同 session 之间不会互相污染
- 如果请求里没有传 `sessionId`，网关会先创建一个临时 session，再基于这个 session 的历史生成并执行代码

### 启动网关

```bash
cd gateway
bun start
```

### 接口

#### 1. 健康检查

```bash
curl http://localhost:3000/health
```

返回示例：

```json
{
  "ok": true,
  "sessionTtlMs": 600000
}
```

#### 2. 创建 sandbox session

```bash
curl -X POST http://localhost:3000/sandbox/sessions
```

返回示例：

```json
{
  "session_id": "sess_xxx",
  "workspace_dir": "/tmp/mini-agent-sandbox/sessions/sess_xxx/workspace",
  "logs_dir": "/tmp/mini-agent-sandbox/sessions/sess_xxx/logs",
  "cleanup_at": "2026-04-25T12:00:00.000Z"
}
```

#### 3. 生成并执行代码

```bash
curl -X POST http://localhost:3000/generate-and-run \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "Write a Python script that prints the first 10 Fibonacci numbers.",
    "fileName": "fibonacci.py",
    "timeoutMs": 5000,
    "scriptArgs": []
  }'
```

返回示例：

```json
{
  "sessionId": "sess_xxx",
  "fileName": "fibonacci.py",
  "filePath": "/tmp/mini-agent-sandbox/sessions/sess_xxx/workspace/fibonacci.py",
  "timeoutMs": 5000,
  "generatedCode": "numbers = [0, 1]\n...",
  "sessionCleanup": {
    "mode": "immediate",
    "cleanup_at": null
  },
  "execution": {
    "success": true,
    "exit_code": 0,
    "stdout": "0 1 1 2 3 5 8 13 21 34\n",
    "stderr": "",
    "timeout": false,
    "duration_ms": 25,
    "truncated": false
  }
}
```

说明：

- 如果请求里**不传** `sessionId`，网关会创建一个临时 session，并在执行结束后**立即清理**。
- 如果请求里**传了** `sessionId`，网关会复用该 session，并把清理时间延后到 `SESSION_TTL_MS`。

#### 4. 直接执行传入代码

```bash
curl -X POST http://localhost:3000/execute-code \
  -H 'Content-Type: application/json' \
  -d '{
    "code": "print(\"hello direct execution\")",
    "fileName": "hello.py",
    "timeoutMs": 5000,
    "scriptArgs": []
  }'
```

返回示例：

```json
{
  "sessionId": "sess_xxx",
  "fileName": "hello.py",
  "filePath": "/tmp/mini-agent-sandbox/sessions/sess_xxx/workspace/hello.py",
  "timeoutMs": 5000,
  "code": "print(\"hello direct execution\")",
  "sessionCleanup": {
    "mode": "immediate",
    "cleanup_at": null
  },
  "execution": {
    "success": true,
    "exit_code": 0,
    "stdout": "hello direct execution\n",
    "stderr": "",
    "timeout": false,
    "duration_ms": 20,
    "truncated": false
  }
}
```

#### 5. 删除 sandbox session

```bash
curl -X DELETE http://localhost:3000/sandbox/sessions/<session_id>
```

#### 6. 查看当前 LLM 配置

```bash
curl http://localhost:3000/config/llm
```

返回会隐藏明文 key，只告诉你是否已配置，以及当前生效的 URL / model 和来源。

#### 7. 持久化更新 LLM 配置

```bash
curl -X PUT http://localhost:3000/config/llm \
  -H 'Content-Type: application/json' \
  -d '{
    "llmApiKey": "your_api_key",
    "llmApiUrl": "https://your-base-url/v1/chat/completions"
  }'
```

说明：

- `llmApiKey`、`llmApiUrl`、`llmModel` 都支持单独更新
- 写入后会保存到 `GATEWAY_CONFIG_PATH` 指向的文件
- 后续 `/generate-and-run` 请求会在请求时动态读取最新配置，无需重启网关

#### 8. 查看最近上下文缓存

```bash
curl 'http://localhost:3000/context/history?sessionId=<session_id>&limit=10'
```

如果不传 `sessionId`，会返回全局持久化缓存视图；但模型注入时仍然只会读取当前 session 的历史。

#### 9. 清空最近上下文缓存

```bash
curl -X DELETE 'http://localhost:3000/context/history?sessionId=<session_id>'
```

如果不传 `sessionId`，会清空全部缓存。

#### 10. 生成并执行时指定本次注入的上下文条数

```bash
curl -X POST http://localhost:3000/generate-and-run \
  -H 'Content-Type: application/json' \
  -d '{
    "prompt": "Write a Python script that reads a csv file and prints the row count.",
    "fileName": "count_rows.py",
    "timeoutMs": 5000,
    "contextLimit": 6,
    "scriptArgs": []
  }'
```

说明：

- `contextLimit` 控制本次调用注入给大模型的最近上下文条数
- 这些缓存现在按 `sessionId` 隔离，注入时只读取当前 session 的最近历史

#### 11. Agent 多步循环 `POST /agent/run`

把单次 `prompt → code → execute` 升级为 `plan → execute → observe → retry` 循环。
模型可以在一次任务内多次调用工具直到目标达成或耗尽预算。

请求体：

```json
{
  "goal": "Generate the first 10 fibonacci numbers and save them to fib.txt, then verify the file content.",
  "sessionId": "sess_xxx",
  "maxSteps": 6,
  "maxConsecutiveFailures": 3,
  "contextLimit": 10,
  "defaultToolTimeoutMs": 5000
}
```

字段说明：

- `goal`（必填）：自然语言任务目标
- `sessionId`（可选）：复用已有 sandbox session；不传时网关创建临时 session 并在结束后立即清理
- `maxSteps`：本次最大循环步数，受 `AGENT_MAX_STEPS` 上限保护（默认 20）
- `maxConsecutiveFailures`：连续工具失败到达该值后中止
- `contextLimit`：注入给模型的历史上下文条数
- `defaultToolTimeoutMs`：`run_python` 工具的默认超时（仍会被 `MAX_TIMEOUT_MS` 收紧）

可用工具（OpenAI function calling 协议）：

| 工具         | 作用                                       |
| ------------ | ------------------------------------------ |
| `write_file` | 在 workspace 写入文本文件                   |
| `run_python` | 执行 workspace 内已存在的 `.py`             |
| `read_file`  | 读取 workspace 内的文本文件                 |
| `list_files` | 列出 workspace 全部文件（递归）             |
| `finish`     | 模型主动声明任务完成，并附最终文字总结      |

返回示例：

```json
{
  "sessionId": "sess_xxx",
  "status": "done",
  "finalAnswer": "Wrote fib.txt with 10 numbers and verified content.",
  "stepsTaken": 3,
  "stepBudget": 6,
  "steps": [
    {
      "step": 1,
      "thought": "I will create the script first.",
      "toolCalls": [{ "name": "write_file", "arguments": { "path": "fib.py", "content": "..." } }],
      "observations": [{ "name": "write_file", "success": true, "observation": { "ok": true, "path": "..." } }]
    },
    { "step": 2, "toolCalls": [{ "name": "run_python", "arguments": { "path": "fib.py" } }], "observations": [{ "success": true, "observation": { "stdout": "0 1 1 2 ...\n", "exit_code": 0 } }] },
    { "step": 3, "toolCalls": [{ "name": "finish", "arguments": { "summary": "..." } }], "observations": [{ "success": true }], "terminator": "finish_tool" }
  ],
  "sessionCleanup": { "mode": "ttl", "cleanup_at": "..." }
}
```

`status` 取值：

- `done` — 模型主动 `finish`，或在没有 tool_calls 的情况下直接给出最终回复
- `forced_stop` — 步数预算耗尽
- `aborted` — 连续工具失败超过阈值

环境变量（新增）：

```bash
export AGENT_DEFAULT_MAX_STEPS=6                 # 默认步数预算
export AGENT_MAX_STEPS=20                        # 单次任务硬上限
export AGENT_DEFAULT_MAX_CONSECUTIVE_FAILURES=3  # 连续失败中止阈值
```

## 当前实现边界

为了先做最简单处理，当前网关采用以下策略：

- 只生成并执行 **Python** 代码
- 通过 **CLI 桥接** Python sandbox，而不是直接嵌入 Python API
- 默认使用 OpenAI 兼容的 `chat/completions` 接口
- 已支持 session 自动回收，但未做多租户鉴权、请求队列、审计增强

这适合作为后续增强版 agent runtime 的最小起点。

## FastAPI 服务（`api/`）

除了 Node.js gateway 之外，仓库还提供了一个 **Python 直连版** FastAPI 服务，
位于 `api/`，与 `sandbox/`、`gateway/` 平级，把 `SandboxService` 直接封装成 HTTP 接口，
并可选接入 DeepSeek 自动生成代码。

### 接口

- `GET  /api/health` — 健康检查
- `POST /api/sessions` — 创建沙盒 session
- `DELETE /api/sessions/{session_id}` — 销毁 session
- `POST /api/sessions/{session_id}/files` — 写入 workspace 文件
- `POST /api/sessions/{session_id}/execute` — 执行命令
- `POST /api/run_code` — 一站式：建 session → 写代码 → 执行 → 清理
- `POST /api/chat_and_run` — 通过 DeepSeek 把自然语言转成代码再执行

CORS 已开放 `*`，便于前端联调。

### 启动

```bash
uv sync                          # 第一次需要，会同时安装 sandbox 与 api
export DEEPSEEK_API_KEY=sk-...   # 仅在使用 /api/chat_and_run 时需要
uv run uvicorn mini_agent_api.server:app --port 8000 --reload
```

打开 `http://localhost:8000/docs` 可使用 Swagger UI 联调。

> `DEEPSEEK_API_KEY` 也可以放在仓库根目录的 `.env` 文件里，`.env` 已经被 gitignore。

## Web 前端（`web/`）

`web/` 下是一个零依赖的纯静态前端（HTML + CSS + 原生 JS），用来调用上面的 FastAPI 服务：

- 左侧代码编辑器、右侧聊天面板、底部终端的三栏布局
- 顶部可配置 API base，支持健康状态轮询
- 主按钮调用 `/api/chat_and_run`；附带「直接运行」按钮调用 `/api/run_code`

### 启动方式

```bash
uv run python -m http.server 5173 --directory web
# 然后访问 http://localhost:5173
```

确保 FastAPI 服务在 `http://localhost:8000` 运行（或在页面顶部输入框里改成实际地址）。

## Docker

```bash
docker build -t mini-agent-sandbox .
docker run --rm mini-agent-sandbox
```

默认会执行 `sandbox-demo demo`。
