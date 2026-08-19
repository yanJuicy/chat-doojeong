"""add work_report_entries table for weekly report feature

채팅/문서 업로드로 들어온 업무 실적·계획 원자료를 정제해서 쌓아두는 테이블.
나중에 특정 기간(주간/월간)으로 조회해서 보고서 양식에 채워 넣는 데 쓴다.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_report_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("department", sa.String(), nullable=False),
        # "실적" 또는 "계획"
        sa.Column("entry_type", sa.String(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        # 원본 표기(사업/관리/시군특화 등) — 느슨한 태그, enum 아님
        sa.Column("source_category", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        # "chat" 또는 "document"
        sa.Column("source", sa.String(), nullable=False),
        # documents.id를 참조하지만 FK 제약은 안 건다 — 원본 문서가 삭제돼도
        # 이미 정제해서 저장한 보고 항목은 남아있어야 하므로 (models.py 참고)
        sa.Column("source_document_id", sa.String(), nullable=True),
        sa.Column("raw_input", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # "이번 주 항목 조회"가 이 테이블의 가장 흔한 쿼리 패턴이라 기간 검색 인덱스를 건다.
    op.create_index(
        "ix_work_report_entries_period", "work_report_entries", ["period_start", "period_end"]
    )
    op.create_index("ix_work_report_entries_department", "work_report_entries", ["department"])


def downgrade() -> None:
    op.drop_index("ix_work_report_entries_department", table_name="work_report_entries")
    op.drop_index("ix_work_report_entries_period", table_name="work_report_entries")
    op.drop_table("work_report_entries")
