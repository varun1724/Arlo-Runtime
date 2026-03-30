"""Add workflows table and workflow columns to jobs

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create workflows table
    op.create_table(
        "workflows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("template_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("context", sa.Text, nullable=False, server_default="{}"),
        sa.Column("step_definitions", sa.Text, nullable=False),
        sa.Column("current_step_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflows_status", "workflows", ["status"])

    # Add workflow columns to jobs table
    op.add_column("jobs", sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflows.id"), nullable=True))
    op.add_column("jobs", sa.Column("step_index", sa.Integer, nullable=True))
    op.create_index("ix_jobs_workflow_id", "jobs", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_workflow_id", table_name="jobs")
    op.drop_column("jobs", "step_index")
    op.drop_column("jobs", "workflow_id")
    op.drop_index("ix_workflows_status", table_name="workflows")
    op.drop_table("workflows")
