"""seed roles and permissions

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10
"""
import sqlalchemy as sa
from alembic import op

from app.core.permissions import PERMISSIONS, ROLES

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

roles = sa.table("roles", sa.column("code", sa.String), sa.column("name", sa.String),
                 sa.column("description", sa.String))
permissions = sa.table("permissions", sa.column("code", sa.String), sa.column("description", sa.String))
role_permissions = sa.table("role_permissions", sa.column("role_code", sa.String),
                            sa.column("permission_code", sa.String))


def upgrade() -> None:
    op.bulk_insert(permissions, [{"code": c, "description": d} for c, d in PERMISSIONS.items()])
    op.bulk_insert(roles, [{"code": c, "name": n, "description": d} for c, (n, d, _) in ROLES.items()])
    op.bulk_insert(role_permissions, [{"role_code": c, "permission_code": p}
                                      for c, (_, _, perms) in ROLES.items() for p in perms])


def downgrade() -> None:
    op.execute("delete from role_permissions")
    op.execute("delete from roles")
    op.execute("delete from permissions")
