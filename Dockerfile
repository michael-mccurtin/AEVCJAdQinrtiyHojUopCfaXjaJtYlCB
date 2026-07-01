# Single image reused by all three services (ingest, api, frontend). The
# service is selected by the command in docker-compose.yml.
FROM python:3.11-slim

# uv for fast, locked dependency installation.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached unless the lockfile changes). --no-dev
# skips test-only deps e.g. pytest.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Application code, the SQL schema, and the raw TMDB CSVs for ingestion.
COPY app ./app
COPY data/tmdb_5000 ./data/tmdb_5000

# Put the project venv on PATH so python/uvicorn/streamlit resolve directly.
ENV PATH="/app/.venv/bin:$PATH"
