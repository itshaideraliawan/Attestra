"""Tenant-scoped persistence operations."""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession

from attestra.models import AiRun, Feedback, Job, TenantPolicy


class TenantRepository[Entity: AiRun | Job | Feedback]:
    """Read and create tenant-owned records within a database session."""

    def __init__(self, session: AsyncSession, model: type[Entity]) -> None:
        self._session = session
        self._model: type[Entity] = model

    async def get(self, tenant_id: str, entity_id: UUID) -> Entity | None:
        """Return a record only when it belongs to the requested tenant."""
        statement = select(self._model).where(
            self._model.tenant_id == tenant_id,
            self._model.id == entity_id,
        )
        return cast(Entity | None, await self._session.scalar(statement))

    async def list(self, tenant_id: str, limit: int = 100) -> list[Entity]:
        """List records for one tenant, bounded to at most 500 results."""
        statement = (
            select(self._model)
            .where(self._model.tenant_id == tenant_id)
            .limit(min(max(limit, 1), 500))
        )
        result: ScalarResult[Entity] = await self._session.scalars(statement)
        return list(result)

    async def create(self, tenant_id: str, values: dict[str, Any]) -> Entity:
        """Create a record owned by the requested tenant."""
        entity = cast(Entity, self._model(tenant_id=tenant_id, **values))
        self._session.add(entity)
        await self._session.flush()
        return entity


class TenantPolicyRepository:
    """Load tenant policy records from a database session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: str) -> TenantPolicy | None:
        """Return the policy assigned to one tenant."""
        statement = select(TenantPolicy).where(TenantPolicy.tenant_id == tenant_id)
        return await self._session.scalar(statement)
