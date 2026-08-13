"""add content_hash column for automatic duplicate detection

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 추출된 raw_text의 SHA256 해시. 크롤러가 같은 페이지를 다른 URL(쿼리스트링만 다름)로
    # 여러 번 문서화해도, 텍스트 추출 후 이 해시로 "내용이 완전히 같은 문서"를 즉시 감지해
    # 청킹/임베딩 낭비 없이 걸러낸다 (extraction_worker에서 사용).
    op.add_column("documents", sa.Column("content_hash", sa.String(), nullable=True))
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_documents_content_hash", table_name="documents")
    op.drop_column("documents", "content_hash")
