"""add weekly report work tracking foundation

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


work_item_status = postgresql.ENUM(
    "planned",
    "in_progress",
    "completed",
    "on_hold",
    name="workitemstatus",
    create_type=False,
)


def upgrade() -> None:
    postgresql.ENUM(
        "planned", "in_progress", "completed", "on_hold", name="workitemstatus"
    ).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "work_items",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("author", sa.String(length=100), nullable=True),
        sa.Column("department", sa.String(length=100), nullable=True),
        sa.Column("status", work_item_status, nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("carry_over", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_items_status", "work_items", ["status"])
    op.create_index("ix_work_items_start_date", "work_items", ["start_date"])
    op.create_index("ix_work_items_due_date", "work_items", ["due_date"])

    op.create_table(
        "work_activities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("work_item_id", sa.String(), nullable=False),
        sa.Column("activity_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", work_item_status, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["work_item_id"], ["work_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_activities_work_item_id", "work_activities", ["work_item_id"])
    op.create_index("ix_work_activities_activity_date", "work_activities", ["activity_date"])

    op.create_table(
        "report_templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("field_schema", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_type", "version", name="uq_report_templates_type_version"),
    )
    op.create_index("ix_report_templates_report_type", "report_templates", ["report_type"])
    op.create_index("ix_report_templates_is_active", "report_templates", ["is_active"])
    # JSON 타입은 Alembic의 오프라인 bulk_insert 리터럴 렌더링을 지원하지 않으므로,
    # 배포 SQL 생성과 실제 마이그레이션에서 모두 같은 결과가 나는 정적 구문을 사용한다.
    op.execute(
        """
        INSERT INTO report_templates
            (id, report_type, name, version, file_path, field_schema, is_active)
        VALUES
            (
                'weekly-default-v1',
                'WEEKLY',
                '주간 업무보고서 기본 양식',
                1,
                'app/report_templates/weekly/default_v1.docx',
                '{"required":["period_start","period_end","cutoff_date","current_week","next_week"]}'::json,
                true
            )
        """
    )

    op.create_table(
        "generated_reports",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("report_type", sa.String(length=50), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("cutoff_date", sa.Date(), nullable=True),
        sa.Column("template_id", sa.String(), nullable=True),
        sa.Column("content_snapshot", sa.JSON(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["report_templates.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generated_reports_report_type", "generated_reports", ["report_type"])


def downgrade() -> None:
    op.drop_index("ix_generated_reports_report_type", table_name="generated_reports")
    op.drop_table("generated_reports")
    op.drop_index("ix_report_templates_is_active", table_name="report_templates")
    op.drop_index("ix_report_templates_report_type", table_name="report_templates")
    op.drop_table("report_templates")
    op.drop_index("ix_work_activities_activity_date", table_name="work_activities")
    op.drop_index("ix_work_activities_work_item_id", table_name="work_activities")
    op.drop_table("work_activities")
    op.drop_index("ix_work_items_due_date", table_name="work_items")
    op.drop_index("ix_work_items_start_date", table_name="work_items")
    op.drop_index("ix_work_items_status", table_name="work_items")
    op.drop_table("work_items")
    work_item_status.drop(op.get_bind(), checkfirst=True)
