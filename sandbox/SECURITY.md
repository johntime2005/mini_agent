# Mini Agent Sandbox — Security Boundaries

This document explains **what `mini_agent_sandbox` is and is not** as a
security boundary. It is intended for downstream integrators who need to
decide whether to trust the sandbox with adversarial input.

## TL;DR

`mini_agent_sandbox` is a **best-effort, defense-in-depth wrapper** around
`subprocess`. It is **not** a strong isolation boundary. Do not feed
adversarial code into it without an additional layer of OS-level
isolation (container, namespace, seccomp, jailed UID, …).

## What the sandbox does

- **Workspace confinement** — all child-process file operations are
  rooted in a per-session `workspace_dir`; path traversal via `..` is
  rejected by `_resolve_workspace_path`.
- **Forbidden-path guard** — `_check_forbidden_path` rejects scripts
  whose resolved location lands on `/etc`, `/proc`, `/sys`, `C:\Windows`,
  etc. Useful when callers pass absolute paths by mistake.
- **AST import filter** — `_validate_python_source` rejects scripts
  containing top-level `import socket` (and similar) at parse time.
- **CPU / memory cap** — when `default_max_cpu_seconds` /
  `default_max_memory_bytes` are configured, `RLIMIT_CPU` /
  `RLIMIT_AS` are applied to the child via `preexec_fn` (Unix only).
- **Wall-clock timeout + process-group kill** — on timeout the entire
  child session group is sent `SIGKILL`, so forked descendants do not
  leak.
- **Audit log** — every accept / reject / start / end / error is emitted
  through the `mini_agent_sandbox.audit` logger.

## What the sandbox does NOT do

The AST scan can be **trivially bypassed** by adversarial code:

```python
__import__("socket")
importlib.import_module("socket")
exec("import socket")
getattr(__builtins__, "__import__")("socket")
```

Likewise:

- **No filesystem isolation beyond the cwd hint** — the child runs as
  the *same UID* as the host process and can therefore read any file
  that UID can read (the AST filter and forbidden-path list only catch
  the *script path*, not subsequent `open()` calls).
- **No network namespace** — even though `socket` is on the import
  blocklist, libraries can still open sockets via C extensions, `os.system`
  pipes, or by spawning external binaries (when `subprocess` import
  ban is bypassed via `os.exec*`).
- **No fork bomb cap** — `RLIMIT_NPROC` is not configured.
- **No syscall filter** — there is no `seccomp` / `prctl` integration.
- **TOCTOU defense is best-effort only** — `service.execute` re-hashes
  the script bytes after `acquire_slot()` and rejects on mismatch; this
  catches casual races but cannot prevent a determined attacker who can
  win between hash and exec.

## Recommended deployment patterns

If you need to run untrusted code, layer one or more of:

1. **Container** with `--network=none --read-only --pids-limit` and a
   non-root user.
2. **Linux namespaces** (`unshare -Uirpfn ...`) plus a writable tmpfs
   `workspace_dir`.
3. **`seccomp` filter** restricting to a small allowlist (`read`,
   `write`, `exit`, `brk`, `mmap`, `rt_sigreturn`).
4. **Dedicated UID** with `chroot` and quota-limited home directory.
5. **Per-tenant VM** for the strongest boundary.

`BaseExecutor` is designed so a future `DockerExecutor` /
`FirecrackerExecutor` / `gVisorExecutor` can slot in without changing
the service layer. PRs welcome.

## Reporting issues

Please open a GitHub issue for non-sensitive policy gaps. For
exploitable escapes that affect deployed users, contact the maintainer
privately first.
