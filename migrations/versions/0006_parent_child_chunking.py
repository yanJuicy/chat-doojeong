"""add parent_text column for parent-child chunking

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Parent-Child 청킹: 검색(임베딩)은 작은 자식 청크(text)로 정밀하게 하되,
    # 답변 생성 시에는 이 청크가 속한 더 큰 맥락(parent_text)을 LLM에게 전달해
    # 맥락 손실을 줄인다. NULL이면 "이 청크 자체가 곧 parent"라는 뜻으로 취급한다
    # (섹션이 굳이 더 안 쪼개진 경우, parent_text를 중복 저장하지 않기 위함).
    op.add_column("document_chunks", sa.Column("parent_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "parent_text")
