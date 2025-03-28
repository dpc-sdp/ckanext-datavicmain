"""Init section item table

Revision ID: 720d557e7d52
Revises:
Create Date: 2024-06-20 11:13:44.498807

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "720d557e7d52"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "home_section_item",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_id", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("entity_url", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("section_type", sa.Text(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("modified_at", sa.DateTime(), nullable=False),
        sa.Column("url_in_new_tab", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("home_section_item")
