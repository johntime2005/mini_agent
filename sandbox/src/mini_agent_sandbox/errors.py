class SandboxError(Exception):
    """Base sandbox error."""


class SessionNotFoundError(SandboxError):
    """Raised when a sandbox session cannot be found."""


class CommandNotAllowedError(SandboxError):
    """Raised when a command is not allowed by policy."""


class ArgumentNotAllowedError(SandboxError):
    """Raised when command arguments are rejected by policy."""


class PathForbiddenError(SandboxError):
    """Raised when a requested path escapes the sandbox workspace."""
