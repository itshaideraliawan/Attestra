"""Persistence models for tenant policy, runs, jobs, and feedback."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base metadata for Attestra persistence models."""


class TenantOwned:
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)


class TenantPolicy(TenantOwned, Base):
    """Tenant configuration controlling AI use."""

    __tablename__ = "tenant_policies"
    __table_args__ = {"schema": "attestra"}

    settings: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AiRun(TenantOwned, Base):
    """Metadata for one AI model run."""

    __tablename__ = "ai_runs"
    __table_args__ = (
        Index("ix_ai_runs_tenant_created", "tenant_id", "created_at"),
        {"schema": "attestra"},
    )

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Job(TenantOwned, Base):
    """Tenant-owned asynchronous work item."""

    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_tenant_status", "tenant_id", "status"),
        {"schema": "attestra"},
    )

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Feedback(TenantOwned, Base):
    """Tenant-owned review feedback for an AI run."""

    __tablename__ = "feedback"
    __table_args__ = (
        Index("ix_feedback_tenant_run", "tenant_id", "ai_run_id"),
        ForeignKeyConstraint(
            ["tenant_id", "ai_run_id"],
            ["attestra.ai_runs.tenant_id", "attestra.ai_runs.id"],
        ),
        {"schema": "attestra"},
    )

    id: Mapped[UUID] = mapped_column(default=uuid4, primary_key=True)
    ai_run_id: Mapped[UUID] = mapped_column(nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
