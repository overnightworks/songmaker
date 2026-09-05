"""Add model mode to user LoRAs.

Revision ID: f41ebd8f5103
Revises: 889dfb248896
Create Date: 2026-09-05

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from songmaker_cli.constants import LORA_TRAINING_MODEL_MODES, MODEL_DEFAULT_MODE

revision: str = "f41ebd8f5103"
down_revision: str | Sequence[str] | None = "889dfb248896"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODEL_MODE_CHECK = "model_mode IN (" + ", ".join(
    repr(mode) for mode in sorted(LORA_TRAINING_MODEL_MODES)
) + ")"


def upgrade() -> None:
    op.add_column(
        "user_loras", sa.Column("model_mode", sa.String(length=10), nullable=True),
    )
    op.execute(
        sa.text("UPDATE user_loras SET model_mode = :model_mode").bindparams(
            model_mode=MODEL_DEFAULT_MODE,
        ),
    )
    with op.batch_alter_table("user_loras") as batch_op:
        batch_op.alter_column(
            "model_mode", existing_type=sa.String(length=10), nullable=False,
        )
        batch_op.create_check_constraint("ck_user_loras_model_mode", _MODEL_MODE_CHECK)


def downgrade() -> None:
    with op.batch_alter_table("user_loras") as batch_op:
        batch_op.drop_constraint("ck_user_loras_model_mode", type_="check")
        batch_op.drop_column("model_mode")
