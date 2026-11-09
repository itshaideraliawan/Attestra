"""Create the tenant policy and work tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261109_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA attestra")
    op.create_table(
        "tenant_policies",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="attestra",
    )
    op.create_table(
        "ai_runs",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="attestra",
    )
    op.create_index(
        "ix_ai_runs_tenant_created", "ai_runs", ["tenant_id", "created_at"], schema="attestra"
    )
    op.create_table(
        "jobs",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="attestra",
    )
    op.create_index("ix_jobs_tenant_status", "jobs", ["tenant_id", "status"], schema="attestra")
    op.create_table(
        "feedback",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "ai_run_id"],
            ["attestra.ai_runs.tenant_id", "attestra.ai_runs.id"],
        ),
        schema="attestra",
    )
    op.create_index(
        "ix_feedback_tenant_run", "feedback", ["tenant_id", "ai_run_id"], schema="attestra"
    )


def downgrade() -> None:
    op.drop_table("feedback", schema="attestra")
    op.drop_table("jobs", schema="attestra")
    op.drop_table("ai_runs", schema="attestra")
    op.drop_table("tenant_policies", schema="attestra")
    op.execute("DROP SCHEMA attestra")
