# Attestra

Attestra is the AI governance service for Stratagix products. It provides a shared, auditable path for model calls. Every AI output is a suggestion for a person to review.

## Local development

Requires Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker Compose.

```powershell
Copy-Item .env.example .env
uv sync --dev
```

Set `ATT_DEV_API_KEY` in `.env` to a locally generated value of at least 32 characters. To run the API directly, set `ATT_DATABASE_URL` to the async PostgreSQL URL for your local database, then start it:

```powershell
uv run uvicorn attestra.app:create_app --factory --reload
```

For Compose, set `ATT_DATABASE_URL` to the async PostgreSQL URL using host `postgres`, and set `POSTGRES_PASSWORD` to the same database password. URL-encode special characters in the password. Apply the schema before starting the container:

```powershell
docker compose run --rm api uv run alembic upgrade head
```

The API listens on `http://localhost:8000`. `/healthz` reports process health, while `/readyz` verifies database connectivity.

To run the API with PostgreSQL 16, set `ATT_DEV_API_KEY`, `ATT_DATABASE_URL`, and `POSTGRES_PASSWORD` in your local `.env` file before starting Compose:

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

## Model providers

Azure OpenAI uses `ATT_AZURE_OPENAI_ENDPOINT`, `ATT_AZURE_OPENAI_API_KEY`, and `ATT_AZURE_OPENAI_DEPLOYMENTS` (a JSON object mapping `fast` and `strong` tiers to deployment names). `ATT_AZURE_OPENAI_API_VERSION` defaults to `v1`. OpenAI-compatible endpoints use `ATT_OPENAI_COMPATIBLE_BASE_URL`, optional `ATT_OPENAI_COMPATIBLE_API_KEY`, and `ATT_OPENAI_COMPATIBLE_MODELS` with the same tier mapping. Providers expose a `pii_allowed` capability flag, false by default; the task pipeline must enforce tenant policy and redaction before sending any prompt. Token cost rates are optional and configured per 1,000 tokens. Provider calls use bounded retries, provider-local circuit breakers, and `ATT_PROVIDER_TIMEOUT_SECONDS`.
