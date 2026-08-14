"""remove unused legacy metadata columns

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("chat_logs", "question_embedding")
    op.drop_column("document_chunks", "precomputed_dense_vector")
    op.drop_column("documents", "category_similarity")
    op.drop_column("documents", "category")
    op.drop_column("documents", "language")


def downgrade() -> None:
    op.add_column("documents", sa.Column("language", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("category", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("category_similarity", sa.Float(), nullable=True))
    op.add_column("document_chunks", sa.Column("precomputed_dense_vector", sa.Text(), nullable=True))
    op.add_column("chat_logs", sa.Column("question_embedding", sa.Text(), nullable=True))
