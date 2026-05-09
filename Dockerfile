# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock ./
COPY sandbox ./sandbox
COPY api ./api
COPY README.md ./

RUN uv sync --frozen --no-dev --package mini-agent-sandbox

ENV PATH="/app/.venv/bin:${PATH}"

CMD ["sandbox-demo", "demo"]
