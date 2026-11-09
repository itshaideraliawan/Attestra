# Attestra

Attestra is the AI governance service for Stratagix products. It provides a shared, auditable path for model calls. Every AI output is a suggestion for a person to review.

## Local development

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker Compose.

```powershell
Copy-Item .env.example .env
uv sync --dev
uv run uvicorn attestra.app:create_app --factory --reload
```

The API listens on `http://localhost:8000`. The health routes are `/healthz` and `/readyz`; readiness is a stub until database integration is implemented.

To run the API with PostgreSQL 16, set `POSTGRES_PASSWORD` in your local `.env` file before starting Compose:

```powershell
docker compose up --build
```

Run quality checks from the repository root:

```powershell
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

Configuration is read from `ATT_`-prefixed environment variables. See `.env.example` for variable names.
