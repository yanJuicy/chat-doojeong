"""주간보고서 미리보기, DOCX 생성 및 이력 다운로드 API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from ..config import settings
from ..db.session import async_session_factory
from ..reports.weekly import WeeklyReportDraft, WeeklyReportRequest, WeeklyReportService
from ..reports.weekly.documents import (
    WeeklyDocumentGenerationError,
    WeeklyDocumentRepository,
    WeeklyDocumentService,
    WeeklyTemplateNotFoundError,
)
from ..services.work_tracking.repository import WorkItemRepository


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_weekly_report_router(session_factory=async_session_factory) -> APIRouter:  # noqa: ANN001
    router = APIRouter(tags=["weekly-reports"])

    @router.post("/api/reports/weekly/generate", response_model=WeeklyReportDraft)
    async def generate_weekly_report(body: WeeklyReportRequest) -> WeeklyReportDraft:
        async with session_factory() as session:
            return await WeeklyReportService(WorkItemRepository(session)).generate(body)

    @router.post(
        "/api/reports/weekly/documents",
        response_class=Response,
        responses={200: {"description": "Generated weekly report DOCX"}},
    )
    async def generate_weekly_document(body: WeeklyReportDraft) -> Response:
        async with session_factory() as session:
            service = WeeklyDocumentService(WeeklyDocumentRepository(session))
            try:
                document = await service.generate(body)
            except WeeklyTemplateNotFoundError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except WeeklyDocumentGenerationError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        return Response(
            content=document.content,
            media_type=document.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{document.filename}"',
                "X-Report-Id": document.report_id,
            },
        )

    @router.get("/api/reports/generated/{report_id}/download", response_class=FileResponse)
    async def download_generated_report(report_id: str) -> FileResponse:
        async with session_factory() as session:
            generated = await WeeklyDocumentRepository(session).get_generated_report(report_id)
        if generated is None or generated.report_type != "WEEKLY" or not generated.file_path:
            raise HTTPException(status_code=404, detail="생성된 보고서를 찾을 수 없습니다.")
        path = Path(generated.file_path).resolve()
        configured = Path(settings.report_storage_dir)
        storage_root = (configured if configured.is_absolute() else _PROJECT_ROOT / configured).resolve()
        if storage_root not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="생성된 보고서 파일을 찾을 수 없습니다.")
        filename = f"weekly-report-{generated.period_start}-{generated.period_end}.docx"
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename=filename,
        )

    return router
