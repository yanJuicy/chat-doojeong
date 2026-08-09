"""add document source_label column

업로드 시 사용자가 직접 지정하는 "어디의 무엇" 라벨. 파일명 추측 대신 이 값을 청크 접두어로 쓴다.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-08

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("source_label", sa.String(), nullable=True))
    op.create_index("ix_documents_source_label", "documents", ["source_label"])


def downgrade() -> None:
    op.drop_index("ix_documents_source_label", table_name="documents")
    op.drop_column("documents", "source_label")
