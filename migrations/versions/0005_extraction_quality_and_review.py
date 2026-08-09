"""add extraction quality gate fields and needs_review status

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'needs_review'")
    op.add_column("documents", sa.Column("extraction_quality_score", sa.Float(), nullable=True))
    op.add_column("documents", sa.Column("extraction_quality_details", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("extraction_method", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("pipeline_version", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "DELETE FROM document_labels a USING document_labels b "
        "WHERE a.document_id = b.document_id AND a.label = b.label AND a.id > b.id"
    )
    op.create_unique_constraint(
        "uq_document_labels_document_label", "document_labels", ["document_id", "label"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_document_labels_document_label", "document_labels", type_="unique")
    op.drop_column("documents", "indexed_at")
    op.drop_column("documents", "pipeline_version")
    op.drop_column("documents", "extraction_method")
    op.drop_column("documents", "extraction_quality_details")
    op.drop_column("documents", "extraction_quality_score")
    # PostgreSQL enum 값 삭제는 테이블 재작성 없이는 안전하지 않으므로 남겨둔다.
