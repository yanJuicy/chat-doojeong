"""initial schema (지금까지 수동 ALTER TABLE로 쌓아온 모든 컬럼 포함)

이 마이그레이션은 지금까지 개발하면서 documents/document_chunks/chat_logs 세 테이블에
하나씩 추가해온 컬럼들(file_hash, category, table_confidence, retry_count,
precomputed_dense_vector 등)을 전부 포함한, models.py 기준 "현재 시점의 완성된 스키마"다.
그동안은 이 변경들을 수동 ALTER TABLE로 하나씩 반영했었는데, 이제부터는 이 파일 하나로
`alembic upgrade head`만 실행하면 새 DB에서도 동일한 스키마가 그대로 재현된다.

Revision ID: 0001
Revises:
Create Date: 2026-08-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DOCUMENT_STATUS_VALUES = ("uploaded", "extracted", "chunked", "ready", "failed")


def upgrade() -> None:
    document_status_enum = sa.Enum(*_DOCUMENT_STATUS_VALUES, name="documentstatus")

    op.create_table(
        "documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("file_hash", sa.String(), nullable=True),
        sa.Column("status", document_status_enum, nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("category_similarity", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("warning_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("is_table", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("table_confidence", sa.Float(), nullable=True),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("embedded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("embed_retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("precomputed_dense_vector", sa.Text(), nullable=True),
    )

    op.create_table(
        "chat_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("question_language", sa.String(), nullable=True),
        sa.Column("question_embedding", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_logs")
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_file_hash", table_name="documents")
    op.drop_table("documents")
    sa.Enum(*_DOCUMENT_STATUS_VALUES, name="documentstatus").drop(op.get_bind(), checkfirst=True)
