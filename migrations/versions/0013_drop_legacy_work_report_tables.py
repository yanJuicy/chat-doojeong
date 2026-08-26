"""drop legacy work_report_entries/work_report_documents, lock document_type_id NOT NULL

scripts/backfill_weekly_reports.py로 데이터 이관 + 검증(RAG 검색/보고서 조합/생성/삭제
스모크 테스트)을 마친 뒤에만 실행한다. docs/DB_확장_구조_설계초안.md 6번 항목 참고 —
검증 없이 구 테이블을 남겨두지 않기로 확정했다.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("documents", "document_type_id", nullable=False)

    op.drop_index("ix_work_report_entries_department", table_name="work_report_entries")
    op.drop_index("ix_work_report_entries_period", table_name="work_report_entries")
    op.drop_table("work_report_entries")
    op.drop_table("work_report_documents")


def downgrade() -> None:
    op.create_table(
        "work_report_documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("department", sa.String(), nullable=True),
        sa.Column("pages_with_table", sa.Integer(), nullable=False),
        sa.Column("pages_without_table", sa.Integer(), nullable=False),
        sa.Column("entries_created", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "work_report_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("department", sa.String(), nullable=False),
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("source_category", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_document_id", sa.String(), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=True),
        sa.Column("source_format", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_work_report_entries_period", "work_report_entries", ["period_start", "period_end"])
    op.create_index("ix_work_report_entries_department", "work_report_entries", ["department"])
    # 주의: 데이터 자체(문서 통합 후 옮겨진 documents 행의 내용)는 downgrade가 복원해주지
    # 않는다 — 구조만 되돌릴 뿐, 백필 이전 데이터로 시간을 되돌리진 못한다.
    op.alter_column("documents", "document_type_id", nullable=True)
