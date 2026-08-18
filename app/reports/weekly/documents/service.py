"""주간보고서 DOCX 생성, 파일 저장, 생성 이력 기록을 조정한다."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

from ....config import settings
from ....db.models import GeneratedReport
from ..models import WeeklyReportDraft
from .docx_renderer import WeeklyDocxRenderer
from .models import WeeklyDocument, WeeklyDocumentGenerationError
from .repository import WeeklyDocumentRepository


_PROJECT_ROOT = Path(__file__).resolve().parents[4]


class WeeklyDocumentService:
    def __init__(
        self,
        repository: WeeklyDocumentRepository,
        renderer: WeeklyDocxRenderer | None = None,
        storage_dir: str | Path | None = None,
    ) -> None:
        self._repository = repository
        self._renderer = renderer or WeeklyDocxRenderer()
        configured = Path(storage_dir or settings.report_storage_dir)
        self._storage_dir = configured if configured.is_absolute() else _PROJECT_ROOT / configured

    @staticmethod
    def _resolve_template_path(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else _PROJECT_ROOT / path

    async def generate(self, report: WeeklyReportDraft) -> WeeklyDocument:
        template = await self._repository.get_active_template()
        template_path = self._resolve_template_path(template.file_path).resolve()
        try:
            content = await asyncio.to_thread(self._renderer.render, report, template_path)
        except Exception as exc:
            raise WeeklyDocumentGenerationError(str(exc)) from exc

        report_id = str(uuid4())
        filename = f"weekly-report-{report.period_start.isoformat()}-{report.period_end.isoformat()}.docx"
        report_dir = (self._storage_dir / str(report.period_start.year)).resolve()
        storage_root = self._storage_dir.resolve()
        if storage_root not in report_dir.parents and report_dir != storage_root:
            raise WeeklyDocumentGenerationError("보고서 저장 경로가 허용된 범위를 벗어났습니다.")
        file_path = report_dir / f"{report_id}.docx"
        try:
            await asyncio.to_thread(report_dir.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(file_path.write_bytes, content)
            await self._repository.add_generated_report(
                GeneratedReport(
                    id=report_id,
                    report_type="WEEKLY",
                    period_start=report.period_start,
                    period_end=report.period_end,
                    cutoff_date=report.cutoff_date,
                    template_id=template.id,
                    content_snapshot=report.model_dump(mode="json"),
                    file_path=str(file_path),
                    status="READY",
                )
            )
        except Exception as exc:
            if file_path.exists():
                await asyncio.to_thread(file_path.unlink)
            raise WeeklyDocumentGenerationError("주간보고서 파일 또는 생성 이력을 저장하지 못했습니다.") from exc
        return WeeklyDocument(
            report_id=report_id,
            content=content,
            filename=filename,
            media_type=self._renderer.media_type,
            file_path=file_path,
        )
