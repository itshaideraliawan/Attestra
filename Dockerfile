FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.11.30 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml README.md uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src
USER app
EXPOSE 8000
CMD ["uvicorn", "attestra.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
