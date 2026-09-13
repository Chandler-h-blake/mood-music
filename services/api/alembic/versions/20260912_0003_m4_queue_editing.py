"""Add M4 queue editing, sorting, refinements, and replay metadata.

Revision ID: 20260912_0003
Revises: 20260912_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260912_0003"
down_revision: str | None = "20260912_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("search_sessions", sa.Column("parent_session_id", sa.Uuid(), nullable=True))
    op.add_column(
        "search_sessions",
        sa.Column(
            "refinements",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "search_sessions",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_foreign_key(
        "search_sessions_parent_session_id_fkey",
        "search_sessions",
        "search_sessions",
        ["parent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "search_candidates",
        sa.Column("user_removed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("generated_playlists", sa.Column("random_seed", sa.BigInteger(), nullable=True))
    op.add_column("generated_playlists", sa.Column("curve", postgresql.JSONB(), nullable=True))
    op.add_column(
        "generated_playlists",
        sa.Column("snapshot_hash", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "playlist_items",
        sa.Column("manually_adjusted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_generated_playlists_created_at", "generated_playlists", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_generated_playlists_created_at", table_name="generated_playlists")
    op.drop_column("playlist_items", "manually_adjusted")
    op.drop_column("generated_playlists", "snapshot_hash")
    op.drop_column("generated_playlists", "curve")
    op.drop_column("generated_playlists", "random_seed")
    op.drop_column("search_candidates", "user_removed")
    op.drop_constraint(
        "search_sessions_parent_session_id_fkey", "search_sessions", type_="foreignkey"
    )
    op.drop_column("search_sessions", "updated_at")
    op.drop_column("search_sessions", "refinements")
    op.drop_column("search_sessions", "parent_session_id")
