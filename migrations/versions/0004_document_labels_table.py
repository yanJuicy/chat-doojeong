"""replace documents.source_label with document_labels table (multi-label)

문서 하나가 여러 라벨(예: "두정테크"+"용접방식")을 동시에 가질 수 있도록,
단일 컬럼(documents.source_label) 대신 별도 테이블로 옮긴다.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_labels",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_labels_document_id", "document_labels", ["document_id"])
    op.create_index("ix_document_labels_label", "document_labels", ["label"])

    # 기존에 documents.source_label에 있던 값을 새 테이블로 옮겨서, 이미 라벨링해둔 문서는 안 잃어버리게 한다.
    op.execute(
        """
        INSERT INTO document_labels (id, document_id, label, created_at)
        SELECT gen_random_uuid()::text, id, source_label, now()
        FROM documents
        WHERE source_label IS NOT NULL
        """
    )

    op.drop_index("ix_documents_source_label", table_name="documents")
    op.drop_column("documents", "source_label")


def downgrade() -> None:
    op.add_column("documents", sa.Column("source_label", sa.String(), nullable=True))
    op.create_index("ix_documents_source_label", "documents", ["source_label"])
    # 문서 하나에 라벨이 여러 개 있었으면(다중라벨 기능을 실제로 쓴 뒤라면) 그중 하나만 남는다 —
    # downgrade는 되돌리기용 안전장치일 뿐이라, 정보 손실 가능성을 감수한다.
    op.execute(
        """
        UPDATE documents
        SET source_label = sub.label
        FROM (
            SELECT DISTINCT ON (document_id) document_id, label
            FROM document_labels
            ORDER BY document_id, created_at
        ) AS sub
        WHERE documents.id = sub.document_id
        """
    )
    op.drop_index("ix_document_labels_label", table_name="document_labels")
    op.drop_index("ix_document_labels_document_id", table_name="document_labels")
    op.drop_table("document_labels")
