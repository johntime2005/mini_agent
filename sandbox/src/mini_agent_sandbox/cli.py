from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .errors import SandboxError
from .service import SandboxService
from .types import SandboxRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a minimal Python sandbox demo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo = subparsers.add_parser("demo", help="Create a session, write a demo script, and execute it")
    demo.add_argument("--timeout-ms", type=int, default=5000)

    run = subparsers.add_parser("run", help="Run a Python script already present in the sandbox workspace")
    run.add_argument("session_id")
    run.add_argument("script")
    run.add_argument("script_args", nargs="*")
    run.add_argument("--timeout-ms", type=int, default=5000)

    create = subparsers.add_parser("create-session", help="Create a new sandbox session")

    write_file = subparsers.add_parser("write-file", help="Write a file into a sandbox workspace")
    write_file.add_argument("session_id")
    write_file.add_argument("relative_path")
    write_file.add_argument("--stdin", action="store_true", dest="read_stdin")
    write_file.add_argument("--content")

    cleanup = subparsers.add_parser("cleanup-session", help="Delete a sandbox session")
    cleanup.add_argument("session_id")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    service = SandboxService()

    if args.command == "create-session":
        session = service.create_session()
        print(json.dumps({
            "session_id": session.session_id,
            "workspace_dir": str(session.workspace_dir),
            "logs_dir": str(session.logs_dir),
        }, indent=2))
        return

    if args.command == "demo":
        session = service.create_session()
        service.write_workspace_file(
            session.session_id,
            "hello.py",
            "import sys\nprint('hello from sandbox')\nprint('args:', sys.argv[1:])\n",
        )
        result = service.execute(
            SandboxRequest(
                session_id=session.session_id,
                command="python",
                args=["hello.py", "mini-agent"],
                timeout_ms=args.timeout_ms,
            )
        )
        print(
            json.dumps(
                {
                    "session_id": session.session_id,
                    "workspace_dir": str(session.workspace_dir),
                    "result": {
                        "success": result.success,
                        "exit_code": result.exit_code,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "timeout": result.timeout,
                        "duration_ms": result.duration_ms,
                        "truncated": result.truncated,
                    },
                },
                indent=2,
            )
        )
        return

    if args.command == "run":
        result = service.execute(
            SandboxRequest(
                session_id=args.session_id,
                command="python",
                args=[args.script, *args.script_args],
                timeout_ms=args.timeout_ms,
            )
        )
        print(
            json.dumps(
                {
                    "success": result.success,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "timeout": result.timeout,
                    "duration_ms": result.duration_ms,
                    "truncated": result.truncated,
                },
                indent=2,
            )
        )
        return

    if args.command == "write-file":
        if args.read_stdin:
            content = sys.stdin.read()
        elif args.content is not None:
            content = args.content
        else:
            parser.error("write-file requires either --stdin or --content")
        target = service.write_workspace_file(args.session_id, args.relative_path, content)
        print(
            json.dumps(
                {
                    "session_id": args.session_id,
                    "relative_path": args.relative_path,
                    "path": str(target),
                },
                indent=2,
            )
        )
        return

    if args.command == "cleanup-session":
        service.cleanup_session(args.session_id)
        print(json.dumps({"session_id": args.session_id, "deleted": True}, indent=2))
        return


if __name__ == "__main__":
    try:
        main()
    except (SandboxError, ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
