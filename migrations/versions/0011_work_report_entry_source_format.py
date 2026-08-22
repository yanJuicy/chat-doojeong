"""add source_format column to work_report_entries

원본 문서 표 셀에서 이 항목이 글머리 기호(•, -)를 썼는지, 기호 없이 문장 하나로
쓰여 있었는지(prose)를 기록해서, 보고서 DOCX를 만들 때 원본 문서의 표현 형식을
그대로 재현할 수 있게 한다.

Revision ID: 0011
Revises: 1f9cfc8c0fe9
Create Date: 2026-08-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "1f9cfc8c0fe9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("work_report_entries", sa.Column("source_format", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("work_report_entries", "source_format")
