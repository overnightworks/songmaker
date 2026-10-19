"""Retain job accounting when an album is permanently deleted."""

from alembic import op

revision = "1968214a67b1"
down_revision = "5f4912bc4a31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("fk_jobs_album_id_albums", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_jobs_album_id_albums", "albums", ["album_id"], ["id"], ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("fk_jobs_album_id_albums", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_jobs_album_id_albums", "albums", ["album_id"], ["id"], ondelete="CASCADE",
        )
