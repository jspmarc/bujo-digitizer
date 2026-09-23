# syntax=docker/dockerfile:1

# ----------
# Stage 1: builder — install dependencies and the project into a venv.
# astral/uv:python3.14-alpine already ships Python 3.14 on Alpine with uv pre-installed.
# ----------
FROM docker.io/astral/uv:python3.14-alpine AS builder

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Compile-time deps for any package without a musllinux wheel
RUN apk add --no-cache build-base

# Install dependencies first so this layer is cached across rebuilds
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-editable

# Install the project itself (uv_build backend bundles prompts, templates, static)
COPY README.md pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# ----------
# Stage 2: runtime — slim image with only the venv (no uv, no source)
# ----------
FROM python:3.14-alpine AS runtime

WORKDIR /app

COPY --from=builder /app/.venv ./.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000

USER root

CMD ["bujo-digitizer"]
