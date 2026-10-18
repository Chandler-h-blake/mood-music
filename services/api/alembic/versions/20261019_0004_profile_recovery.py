"""Add fenced worker leases and profile evidence snapshots.

Revision ID: 20261019_0004
Revises: 20260912_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261019_0004"
down_revision: str | None = "20260912_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("index_jobs", sa.Column("lease_owner", sa.String(64), nullable=True))
    op.add_column(
        "index_jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_index_jobs_status_lease", "index_jobs", ["status", "lease_expires_at"])
    op.add_column(
        "song_profiles",
        sa.Column(
            "manual_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("search_sessions", sa.Column("diagnostics", postgresql.JSONB(), nullable=True))
    op.add_column("search_candidates", sa.Column("explanation", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("search_candidates", "explanation")
    op.drop_column("search_sessions", "diagnostics")
    op.drop_column("song_profiles", "manual_locked")
    op.drop_index("ix_index_jobs_status_lease", table_name="index_jobs")
    op.drop_column("index_jobs", "lease_expires_at")
    op.drop_column("index_jobs", "lease_owner")
