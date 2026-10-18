# API — FastAPI + uv. Railway/any-container deploy.
# Built from the REPO ROOT so the image also gets packages/engine, which the /engine routes
# import (Railway: root directory blank, config in /railway.toml):
#   docker build -f apps/api/Dockerfile .
FROM python:3.12-slim

# uv (fast, reproducible installs from uv.lock)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Same layout as the repo: the API at /repo/apps/api, the engine at /repo/packages/engine.
WORKDIR /repo/apps/api

# Install dependencies first (better layer caching), then the app.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY packages/engine /repo/packages/engine
COPY apps/api/ .
RUN uv sync --frozen --no-dev

# Railway injects $PORT; default 8000 for local `docker run`.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
