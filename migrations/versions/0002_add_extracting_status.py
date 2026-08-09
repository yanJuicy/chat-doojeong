"""add extracting status and page progress columns

업로드 즉시 응답 + 페이지 단위 진행률("3/32페이지 처리 중") 표시를 위한 변경.
documents.status enum에 'extracting' 값을 추가하고, 진행률 컬럼 두 개를 추가한다.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL 12+ 는 ALTER TYPE ... ADD VALUE를 트랜잭션 안에서 실행할 수 있다
    # (단, 같은 트랜잭션 안에서 그 새 값을 바로 사용하는 것은 안 됨 — 여기선 값 추가만 하므로 문제 없음).
    op.execute("ALTER TYPE documentstatus ADD VALUE IF NOT EXISTS 'extracting'")
    op.add_column("documents", sa.Column("current_page", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("total_pages", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "total_pages")
    op.drop_column("documents", "current_page")
    # PostgreSQL은 enum에서 값을 빼는 게 기본적으로 지원 안 됨(타입을 통째로 재생성해야 함) — downgrade에선 값은 그대로 둔다.
