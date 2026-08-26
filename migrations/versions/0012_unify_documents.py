"""unify documents table: document_types lookup + type_specific_data JSONB

docs/DB_확장_구조_설계초안.md 참고. 스키마 변경만 여기서 하고, work_report_entries/
work_report_documents의 실제 데이터 이관은 별도 백필 스크립트(scripts/backfill_weekly_reports.py)로
진행한다 — 임베딩 재생성처럼 SQL만으로 못 하는 작업이 섞여 있어서 마이그레이션에 넣지 않는다.
백필 검증 끝나면 0013에서 document_type_id를 NOT NULL로 잠그고 구 테이블을 지운다.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "document_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(), nullable=False, unique=True),
        sa.Column("label", sa.String(), nullable=False),
    )
    document_types = sa.table(
        "document_types",
        sa.column("id", sa.Integer()),
        sa.column("code", sa.String()),
        sa.column("label", sa.String()),
    )
    op.bulk_insert(
        document_types,
        [
            {"id": 1, "code": "rag_upload", "label": "일반 업로드 문서"},
            {"id": 2, "code": "weekly_report_entry", "label": "주간보고서 항목"},
            {"id": 3, "code": "weekly_report_source", "label": "주간보고서 원본 문서"},
        ],
    )

    op.add_column("documents", sa.Column("document_type_id", sa.Integer(), nullable=True))
    op.create_index("ix_documents_document_type_id", "documents", ["document_type_id"])
    op.create_foreign_key(
        "fk_documents_document_type_id", "documents", "document_types", ["document_type_id"], ["id"]
    )
    op.add_column("documents", sa.Column("subject", sa.String(), nullable=True))
    op.create_index("ix_documents_subject", "documents", ["subject"])
    op.add_column("documents", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("content", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("source", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("source_document_id", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("raw_input", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("type_specific_data", postgresql.JSONB(), nullable=True))

    # 기존 documents 행은 전부 지금까지 해오던 대로 RAG 업로드 문서다.
    op.execute("UPDATE documents SET document_type_id = 1 WHERE document_type_id IS NULL")


def downgrade() -> None:
    op.drop_column("documents", "type_specific_data")
    op.drop_column("documents", "raw_input")
    op.drop_column("documents", "source_document_id")
    op.drop_column("documents", "source")
    op.drop_column("documents", "content")
    op.drop_column("documents", "period_end")
    op.drop_column("documents", "period_start")
    op.drop_index("ix_documents_subject", table_name="documents")
    op.drop_column("documents", "subject")
    op.drop_constraint("fk_documents_document_type_id", "documents", type_="foreignkey")
    op.drop_index("ix_documents_document_type_id", table_name="documents")
    op.drop_column("documents", "document_type_id")
    op.drop_table("document_types")
