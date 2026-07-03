# Multi-stage build: frontend static files are baked into the backend image so
# the whole app is a single container serving one origin.

# --- Stage 1: build the frontend ---------------------------------------------
FROM node:22-alpine AS frontend-build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# --- Stage 2: backend deps -----------------------------------------------------
FROM python:3.12-slim AS backend-base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --no-dev --no-install-project
ENV PATH="/opt/venv/bin:$PATH"

# Dev target: source is bind-mounted by docker-compose.dev.yml
FROM backend-base AS backend-dev
RUN uv sync --no-install-project
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

# --- Stage 3: production --------------------------------------------------------
FROM backend-base AS production
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY --from=frontend-build /src/dist ./static

ENV DATA_DIR=/data STATIC_DIR=/app/static
EXPOSE 8080
# Single worker is intentional: the in-process WebSocket hub and SQLite writer
# assume one process. Do not scale this horizontally without re-architecting.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
