# Single-stage build: use the Playwright image directly so the venv's
# Python symlinks always match the runtime Python binary.
FROM ghcr.io/astral-sh/uv:0.6.17 AS uv-bin

FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy

COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /app

# Store uv-managed Python under /app so it's included in the chown below.
ENV UV_PYTHON_INSTALL_DIR=/app/.uv-python

# --- Dependency layer (cache-friendly) ---
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project --no-cache

# --- Source layer ---
COPY src/ ./src/
RUN uv pip install --no-deps .

# --- Playwright Python package ---
# `playwright` is dev-only in pyproject.toml so --no-dev excluded it.
# The base image already ships Chromium; we only need the Python bindings.
RUN VIRTUAL_ENV=/app/.venv uv pip install "playwright==1.59.0"

# --- Non-root user ---
RUN useradd -m -u 1001 app
RUN chown -R app:app /app

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RUN_ENV=prod

USER app

# --- Health check ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD be-leads-validate-kbo 0434158858 || exit 1

# No CMD / ENTRYPOINT — invoked via `docker compose run`:
#   docker compose run --rm pipeline be-leads-pipeline-batch --city antwerpen --all-sectors
#   docker compose run --rm migrate
