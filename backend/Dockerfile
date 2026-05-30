# ---- Build stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source
COPY src/ ./src/
COPY gunicorn.conf.py ./
COPY migrations/ ./migrations/

# ---- Runtime stage ----
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install curl (healthcheck) and postgresql-client (migrations)
RUN apt-get update && apt-get install -y --no-install-recommends curl postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copy virtual env and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src ./src
COPY --from=builder /app/gunicorn.conf.py ./
COPY --from=builder /app/migrations ./migrations
COPY entrypoint.sh ./entrypoint.sh

# Set PATH to use the virtual env
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Switch to non-root user
USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "src.api.app:app", "-c", "gunicorn.conf.py"]
