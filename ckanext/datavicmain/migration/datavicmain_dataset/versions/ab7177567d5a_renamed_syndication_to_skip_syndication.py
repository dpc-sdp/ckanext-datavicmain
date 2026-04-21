"""renamed syndication to skip_syndication

Revision ID: ab7177567d5a
Revises:
Create Date: 2026-03-17 05:20:30.263834

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'ab7177567d5a'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE package_extra
        SET key = 'skip_syndication', value = 'false'
        WHERE key = 'syndicate'
    """)


def downgrade():
    pass
