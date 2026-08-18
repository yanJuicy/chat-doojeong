"""add chat_sessions and chat_turns tables for multi-turn chat

멀티턴 채팅(질문 재작성 레이어)이 대화 이력을 저장/조회하는 데 쓰는 테이블 두 개.
기존 chat_logs(일일보고서 참고자료 검색용, 대화 구분 없는 평면 로그)와는 용도가
달라서 건드리지 않고 새 테이블로 분리한다.

Revision ID: 0009
Revises: 0006
Create Date: 2026-08-18

주의: 원래 이 마이그레이션은 down_revision="0008"(사위님의 Parent-Child 청킹/content_hash 중복제거,
th-backend-compat 후반 커밋)이었다. 이 브랜치는 그 작업을 의도적으로 제외한 기준(95cc3e7 +
이유빈님 출하보고서)이라 0007/0008이 체인에 없다. 0009는 chat_sessions/chat_turns 신규 테이블만
만들고 0007/0008이 건드리는 어떤 컬럼도 참조하지 않아서, 0006 바로 위로 연결점만 옮겼다
(실제 스키마 변경 내용은 원본과 동일).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        # FE(crypto.randomUUID())가 만든 값을 그대로 PK로 쓴다 — 서버가 별도 발급 안 함.
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "chat_turns",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("chat_sessions.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),  # "user" | "assistant"
        sa.Column("content", sa.Text(), nullable=False),
        # user 행에만 채워짐: 질문 재작성이 실제로 검색에 넘긴 standalone 질문 (디버깅용)
        sa.Column("rewritten_question", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_turns_session_id", "chat_turns", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_turns_session_id", table_name="chat_turns")
    op.drop_table("chat_turns")
    op.drop_table("chat_sessions")
