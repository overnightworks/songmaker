"""Create reference_recordings: every uploaded reference audio file is a row."""

import sqlalchemy as sa
from alembic import op

revision = "5b2e9d4a7c31"
down_revision = "c4e8a1f72d95"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reference_recordings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("storage_path", sa.Text(), nullable=False, unique=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_reference_recordings_user_id"), table_name="reference_recordings")
    op.drop_table("reference_recordings")
