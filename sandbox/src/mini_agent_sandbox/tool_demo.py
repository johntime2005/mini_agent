from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .service import SandboxService
from .types import SandboxRequest


def run_python_tool(
    code: str,
    *,
    script_path: str = "tool.py",
    script_args: list[str] | None = None,
    timeout_ms: int = 5000,
    cleanup: bool = True,
) -> dict[str, Any]:
    """Run dynamically provided Python code inside the sandbox.

    This is a small callable wrapper around ``SandboxService`` suitable for
    embedding in other Python code as a tool-like function.
    """

    service = SandboxService()
    session = service.create_session()
    try:
        target = service.write_workspace_file(session.session_id, script_path, code)
        result = service.execute(
            SandboxRequest(
                session_id=session.session_id,
                command="python",
                args=[script_path, *(script_args or [])],
                timeout_ms=timeout_ms,
            )
        )
        return {
            "session_id": session.session_id,
            "workspace_dir": str(session.workspace_dir),
            "script_path": str(Path(target).relative_to(session.workspace_dir)),
            "result": asdict(result),
        }
    finally:
        if cleanup:
            service.cleanup_session(session.session_id)


def word_count_tool(text: str) -> dict[str, Any]:
    """Example callable tool built on top of the sandbox wrapper."""

    code = """
import json
import sys

text = sys.argv[1]
words = text.split()
payload = {
    "text": text,
    "word_count": len(words),
    "unique_word_count": len(set(word.lower() for word in words)),
    "longest_word": max(words, key=len, default=""),
}
print(json.dumps(payload, ensure_ascii=False))
""".strip()
    execution = run_python_tool(code, script_args=[text])
    stdout = execution["result"]["stdout"].strip()
    execution["parsed_output"] = json.loads(stdout) if stdout else None
    return execution


def main() -> None:
    sample = "mini agent sandbox makes tool calling easy"
    output = word_count_tool(sample)
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
