from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from mini_agent_sandbox.errors import SessionNotFoundError
from mini_agent_sandbox.service import SandboxService
from mini_agent_sandbox.types import SandboxRequest

from .ai_service import AIServiceError, generate_python_code


# ---------- Schemas ----------

class SessionResponse(BaseModel):
    session_id: str
    workspace_dir: str
    logs_dir: str


class WriteFileRequest(BaseModel):
    relative_path: str = Field(..., description="Workspace-relative file path")
    content: str = Field(..., description="UTF-8 file content")


class WriteFileResponse(BaseModel):
    session_id: str
    path: str


class ExecuteRequest(BaseModel):
    command: str = Field(..., description="Command to execute, e.g. 'python'")
    args: list[str] = Field(default_factory=list)
    timeout_ms: int = 5000


class ExecuteResponse(BaseModel):
    success: bool
    exit_code: int | None
    stdout: str
    stderr: str
    timeout: bool
    duration_ms: int
    truncated: bool


class RunCodeRequest(BaseModel):
    code: str = Field(..., description="Python source code to run")
    filename: str = Field(default="main.py")
    command: str = Field(default="python")
    extra_args: list[str] = Field(default_factory=list)
    timeout_ms: int = 5000
    keep_session: bool = False


class RunCodeResponse(BaseModel):
    session_id: str
    result: ExecuteResponse


class ChatAndRunRequest(BaseModel):
    prompt: str = Field(..., description="Natural language requirement for the AI")
    model: str = Field(default="deepseek-chat")
    filename: str = Field(default="main.py")
    timeout_ms: int = 10000
    keep_session: bool = False


class ChatAndRunResponse(BaseModel):
    session_id: str
    prompt: str
    model: str
    code: str
    result: ExecuteResponse


# ---------- App ----------

app = FastAPI(title="Mini Agent Sandbox API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

service = SandboxService()


def _result_to_response(result: Any) -> ExecuteResponse:
    return ExecuteResponse(**asdict(result))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/sessions", response_model=SessionResponse)
def create_session() -> SessionResponse:
    session = service.create_session()
    return SessionResponse(
        session_id=session.session_id,
        workspace_dir=str(session.workspace_dir),
        logs_dir=str(session.logs_dir),
    )


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str) -> dict[str, str]:
    try:
        service.cleanup_session(session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"session_id": session_id, "status": "deleted"}


@app.post("/api/sessions/{session_id}/files", response_model=WriteFileResponse)
def write_file(session_id: str, body: WriteFileRequest) -> WriteFileResponse:
    try:
        path = service.write_workspace_file(session_id, body.relative_path, body.content)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WriteFileResponse(session_id=session_id, path=str(path))


@app.post("/api/sessions/{session_id}/execute", response_model=ExecuteResponse)
def execute(session_id: str, body: ExecuteRequest) -> ExecuteResponse:
    request = SandboxRequest(
        session_id=session_id,
        command=body.command,
        args=list(body.args),
        timeout_ms=body.timeout_ms,
    )
    try:
        result = service.execute(request)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result_to_response(result)


@app.post("/api/run_code", response_model=RunCodeResponse)
def run_code(body: RunCodeRequest) -> RunCodeResponse:
    session = service.create_session()
    try:
        service.write_workspace_file(session.session_id, body.filename, body.code)
        request = SandboxRequest(
            session_id=session.session_id,
            command=body.command,
            args=[body.filename, *body.extra_args],
            timeout_ms=body.timeout_ms,
        )
        result = service.execute(request)
    except Exception as exc:
        service.cleanup_session(session.session_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = RunCodeResponse(
        session_id=session.session_id,
        result=_result_to_response(result),
    )
    if not body.keep_session:
        service.cleanup_session(session.session_id)
    return response


@app.post("/api/chat_and_run", response_model=ChatAndRunResponse)
async def chat_and_run(body: ChatAndRunRequest) -> ChatAndRunResponse:
    try:
        code = await generate_python_code(body.prompt, model=body.model)
    except AIServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    session = service.create_session()
    try:
        service.write_workspace_file(session.session_id, body.filename, code)
        request = SandboxRequest(
            session_id=session.session_id,
            command="python",
            args=[body.filename],
            timeout_ms=body.timeout_ms,
        )
        result = service.execute(request)
    except Exception as exc:
        service.cleanup_session(session.session_id)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = ChatAndRunResponse(
        session_id=session.session_id,
        prompt=body.prompt,
        model=body.model,
        code=code,
        result=_result_to_response(result),
    )
    if not body.keep_session:
        service.cleanup_session(session.session_id)
    return response
