# Attestra

Attestra is the AI governance service for Stratagix products. It provides a shared, auditable path for model calls. Every AI output is a suggestion for a person to review.

## Local development

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker Compose.

```powershell
Copy-Item .env.example .env
uv sync --dev
```

Set `ATT_DEV_API_KEY` in `.env` to a locally generated value of at least 32 characters, then start the API:

```powershell
uv run uvicorn attestra.app:create_app --factory --reload
```

The API listens on `http://localhost:8000`. The health routes are `/healthz` and `/readyz`; readiness is a stub until database integration is implemented.

To run the API with PostgreSQL 16, set both `ATT_DEV_API_KEY` and `POSTGRES_PASSWORD` in your local `.env` file before starting Compose:

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

## Authentication

Local development uses `ATT_AUTH_MODE=api_key` and requires a randomly generated `ATT_DEV_API_KEY` of at least 32 characters. The service refuses API key mode outside the development environment. For Entra ID, set `ATT_AUTH_MODE=entra`, `ATT_ENTRA_ISSUER`, `ATT_ENTRA_AUDIENCE`, and `ATT_ENTRA_ALLOWED_CLIENTS` (a JSON array of client IDs). Protected requests include `X-Tenant-Id` and `X-User-Id`; Entra requests also include an `Authorization: Bearer` access token.
