"""a community is told of staff access

``access_grants`` gains ``community_notice``: whether, and when, the
community's superadmins are emailed that platform staff hold the grant —
``none``, ``when_granted`` or ``when_ended``. Existing rows take the ``none``
server default, which is what they already were.

Revision ID: 20261028_0551
Revises: 20261027_0550
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

revision = "20261028_0551"
down_revision = "20261027_0550"
branch_labels = None
depends_on = None

_CK = "ck_access_grants_community_notice"

#: The values as of THIS revision, spelled out for the reason 0166 gives.
_NOTICES = ("none", "when_granted", "when_ended")


def upgrade() -> None:
    op.add_column(
        "access_grants",
        sa.Column(
            "community_notice",
            sa.String(length=16),
            nullable=False,
            server_default="none",
        ),
    )
    op.create_check_constraint(
        _CK, "access_grants", sa.column("community_notice").in_(_NOTICES)
    )


def downgrade() -> None:
    op.drop_constraint(_CK, "access_grants", type_="check")
    op.drop_column("access_grants", "community_notice")
