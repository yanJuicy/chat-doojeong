"""활성 DOCX 양식과 생성 보고서 이력을 관리한다."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....db.models import GeneratedReport, ReportTemplate
from .models import WeeklyTemplateNotFoundError


class WeeklyDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_template(self) -> ReportTemplate:
        result = await self._session.execute(
            select(ReportTemplate)
            .where(ReportTemplate.report_type == "WEEKLY", ReportTemplate.is_active.is_(True))
            .order_by(ReportTemplate.version.desc())
            .limit(1)
        )
        template = result.scalar_one_or_none()
        if template is None:
            raise WeeklyTemplateNotFoundError("활성화된 주간보고서 양식이 없습니다.")
        return template

    async def add_generated_report(self, report: GeneratedReport) -> None:
        self._session.add(report)
        await self._session.commit()

    async def get_generated_report(self, report_id: str) -> GeneratedReport | None:
        return await self._session.get(GeneratedReport, report_id)
