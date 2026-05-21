# =============================================================================
# Stage 1 — builder
# Install production Python dependencies and build the project wheel.
# Uses python:3.12-slim to keep the build environment minimal.
# =============================================================================
FROM ghcr.io/astral-sh/uv:0.6.17 AS uv-bin

FROM python:3.12-slim AS builder

# Copy uv binary from official image
COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /app

# --- Dependency layer (cache-friendly) ---
# Copy lockfiles first so this layer is only invalidated when deps change.
COPY pyproject.toml uv.lock ./

# Install production dependencies into /app/.venv (no dev extras, no project yet)
RUN uv sync --locked --no-dev --no-install-project --no-cache

# --- Source layer ---
COPY src/ ./src/

# Install the project package (no-deps: deps already in venv above)
# This wires up the [project.scripts] CLI entrypoints.
RUN uv pip install --no-deps .

# =============================================================================
# Stage 2 — runtime
# Playwright base image has Chromium pre-installed and sets
# PLAYWRIGHT_BROWSERS_PATH to the correct location.
# We layer our venv on top and add the playwright Python package.
# =============================================================================
FROM mcr.microsoft.com/playwright/python:v1.59.0-jammy AS runtime

# Copy uv into the runtime image (used for post-install pip invocations)
COPY --from=uv-bin /uv /usr/local/bin/uv

WORKDIR /app

# Bring the entire built venv + source from the builder stage
COPY --from=builder /app /app

# --- Non-root user (created before playwright install so browsers land in app's home) ---
RUN useradd -m -u 1000 app
RUN chown -R app:app /app

# --- Runtime environment ---
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV RUN_ENV=prod

USER app

# --- playwright Python package ---
# `playwright` lives in [dependency-groups] dev, so --no-dev excluded it.
# The base image provides Chromium; we only need the Python bindings in our venv.
# Pin to match the base image version to avoid browser revision mismatch.
RUN /app/.venv/bin/pip install "playwright==1.59.0"

# Link to Chromium pre-installed in the base image (no download needed).
RUN /app/.venv/bin/playwright install chromium

# --- Health check ---
# Validates that CLI entrypoints are wired up and the KBO checksum logic works.
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD be-leads-validate-kbo 0434158858 || exit 1

# No CMD / ENTRYPOINT — invoked via `docker compose run` with explicit commands:
#   docker compose run --rm app be-leads-pipeline-batch --city antwerpen --sector elektriciens
#   docker compose run --rm app be-leads-migrate
