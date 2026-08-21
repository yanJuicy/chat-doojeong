"""
주간 업무보고 원자료 API.

POST /api/v1/work-reports/upload-document
  기존 주간보고서 문서(PDF)를 업로드하면, 페이지마다 표를 감지해서
  report_table_parser.parse_report_table()로 구조화한 뒤 work_report_entries에 저장한다.
  이 경로는 일반 RAG 문서 업로드(/api/v1/upload)와 별개다 — 검색용 청킹/임베딩이
  아니라, 표 자체를 구조화된 레코드로 뽑아내는 게 목적이라 워커 파이프라인을 안 태운다.
  텍스트 레이어가 있는 디지털 페이지는 find_tables()(좌표 기반, OCR 불필요)로,
  텍스트가 없는 스캔 페이지는 PPStructureV3 OCR로 표를 인식해 같은 그리드 형태로
  변환한다 — 원본이 스캔한 사진이어도 동작하게 하려는 목적. 단, 두 경로 모두 병합
  셀은 지원하지 않는 간이 파서라, 병합 셀이 있는 표는 구분이 어긋날 수 있다.

GET /api/v1/work-reports
  기간(start~end)/부서로 저장된 항목을 조회한다. 보고서를 뽑기 전에 "지금까지 뭐가
  쌓였는지" 확인하거나, 다음 단계(양식 채우기)에서 재료로 쓸 데이터를 가져올 때 쓴다.

POST /api/v1/work-reports/chat-entry
  "주간보고서 모드" 채팅에서 자유롭게 입력한 텍스트를 report_chat_refiner로 정제해서
  (여러 사실 분리 + 실적/계획 판단) work_report_entries에 저장한다. 문서 경로와 달리
  구조가 없는 자유 텍스트라 LLM이 관여한다 — 실패해도 원문은 실적 항목 하나로 보존된다.

GET /api/v1/work-reports/report
  기간/부서로 쌓인 항목을 모아 타겟 양식(구분 1개) 기준 JSON으로 미리보기를 준다.
  프론트가 이 JSON을 보여주고 사용자가 항목을 확인/수정한 뒤 확정하는 용도.

GET /api/v1/work-reports/report.docx
  위와 같은 데이터를 원본 양식과 같은 모양의 DOCX 파일로 바로 내려준다.

PATCH /api/v1/work-reports/{entry_id}
  저장된 항목 하나의 내용을 수정한다 (오타 정정, 문구 다듬기 등).

DELETE /api/v1/work-reports/{entry_id}
  저장된 항목 하나를 삭제한다 (잘못 들어간 항목 제거).
"""
from __future__ import annotations

import io
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import quote

import fitz  # PyMuPDF
from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select

from ..config import settings
from ..core.report_chat_refiner import refine_chat_input
from ..core.report_table_parser import parse_report_table
from ..core.weekly_report_composer import compose_weekly_report
from ..core.weekly_report_docx_renderer import render_weekly_report_docx
from ..core.work_report_indexing import deindex_entry, index_entry
from ..db.models import WorkReportDocument, WorkReportEntry
from ..db.session import async_session_factory
from ..services.table_extraction.engines.paddle_engine import PaddleTableEngine


def _render_page_to_image(page, dpi: int) -> Image.Image:  # noqa: ANN001 — fitz.Page는 외부 라이브러리 타입
    """스캔 페이지를 OCR용 이미지로 렌더링한다 (PdfExtractor._render_page_to_image와 동일 로직)."""
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    return Image.open(io.BytesIO(pix.tobytes("png")))


class ChatEntryRequest(BaseModel):
    department: str
    text: str
    current_period_start: date
    current_period_end: date
    next_period_start: date
    next_period_end: date


class UpdateEntryRequest(BaseModel):
    content: str


def create_work_reports_router(upload_dir: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v1/work-reports", tags=["work-reports"])

    @router.post("/upload-document")
    async def upload_document(request: Request, file: UploadFile) -> JSONResponse:
        safe_filename = Path(file.filename or "report.pdf").name
        if Path(safe_filename).suffix.lower() != ".pdf":
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "지금은 PDF만 지원합니다 (DOCX/XLSX/HWP는 추후 지원 예정).",
                    },
                },
            )

        file_bytes = await file.read()
        document_id = str(uuid.uuid4())
        saved_path = upload_dir / f"work-report_{document_id}_{safe_filename}"
        saved_path.write_bytes(file_bytes)

        try:
            pdf = fitz.open(stream=file_bytes, filetype="pdf")
        except Exception as exc:  # noqa: BLE001 — 손상된 파일은 사용자에게 바로 알린다
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {"code": "PARSE_ERROR", "message": f"PDF를 열 수 없습니다: {exc}"},
                },
            )

        entries_to_save: list[WorkReportEntry] = []
        pages_with_table = 0
        pages_without_table: list[int] = []
        pages_via_ocr: list[int] = []
        paddle_engine: PaddleTableEngine | None = None

        try:
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                digital_text = page.get_text()

                # (rows 그리드, 주변 텍스트) 쌍의 목록 — 디지털/OCR 어느 경로든 같은 모양으로 맞춘다.
                grids_with_context: list[tuple[list[list[str]], str]] = []

                if digital_text.strip():
                    # 텍스트 레이어가 있는 디지털 페이지: find_tables()로 좌표 기반 감지 (OCR 불필요)
                    found = page.find_tables()
                    for table in found.tables:
                        grids_with_context.append((table.extract(), digital_text))
                else:
                    # 텍스트 레이어가 없는 스캔 페이지: PPStructureV3 OCR로 표를 인식한다.
                    if paddle_engine is None:
                        paddle_engine = PaddleTableEngine()
                    image = _render_page_to_image(page, settings.scan_render_dpi)
                    grids, ocr_text = paddle_engine.extract_tables_as_grids(image)
                    for grid in grids:
                        grids_with_context.append((grid, ocr_text))
                    if grids:
                        pages_via_ocr.append(page_index + 1)

                if not grids_with_context:
                    pages_without_table.append(page_index + 1)
                    continue

                pages_with_table += 1
                for rows, context_text in grids_with_context:
                    for parsed in parse_report_table(rows, context_text):
                        entries_to_save.append(
                            WorkReportEntry(
                                id=str(uuid.uuid4()),
                                department=parsed.department,
                                entry_type=parsed.entry_type,
                                period_start=parsed.period_start,
                                period_end=parsed.period_end,
                                source_category=parsed.source_category,
                                content=parsed.content,
                                source="document",
                                source_document_id=document_id,
                            )
                        )
        finally:
            pdf.close()

        async with async_session_factory() as session:
            session.add(
                WorkReportDocument(
                    id=document_id,
                    filename=safe_filename,
                    file_path=str(saved_path),
                    department=entries_to_save[0].department if entries_to_save else None,
                    pages_with_table=pages_with_table,
                    pages_without_table=len(pages_without_table),
                    entries_created=len(entries_to_save),
                )
            )
            session.add_all(entries_to_save)
            await session.commit()

            embedding_provider = request.app.state.embedding_provider
            vector_store = request.app.state.vector_store
            for entry in entries_to_save:
                await index_entry(session, embedding_provider, vector_store, entry)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": {
                    "document_id": document_id,
                    "filename": safe_filename,
                    "department": entries_to_save[0].department if entries_to_save else None,
                    "pages_total": pages_with_table + len(pages_without_table),
                    "pages_with_table": pages_with_table,
                    "pages_without_table": pages_without_table,
                    "pages_via_ocr": pages_via_ocr,
                    "entries_created": len(entries_to_save),
                },
            },
        )

    @router.post("/chat-entry")
    async def chat_entry(request: Request, body: ChatEntryRequest) -> JSONResponse:
        llm_provider = request.app.state.llm_provider
        refined = await refine_chat_input(body.text, llm_provider)

        entries_to_save = [
            WorkReportEntry(
                id=str(uuid.uuid4()),
                department=body.department,
                entry_type=item.entry_type,
                period_start=body.current_period_start if item.entry_type == "실적" else body.next_period_start,
                period_end=body.current_period_end if item.entry_type == "실적" else body.next_period_end,
                source_category=None,
                content=item.content,
                source="chat",
                raw_input=body.text,
            )
            for item in refined
        ]

        async with async_session_factory() as session:
            session.add_all(entries_to_save)
            await session.commit()

            embedding_provider = request.app.state.embedding_provider
            vector_store = request.app.state.vector_store
            for entry in entries_to_save:
                await index_entry(session, embedding_provider, vector_store, entry)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": {
                    "entries_created": len(entries_to_save),
                    "entries": [
                        {"id": entry.id, "entry_type": entry.entry_type, "content": entry.content}
                        for entry in entries_to_save
                    ],
                },
            },
        )

    @router.get("/report")
    async def get_report(
        department: str,
        current_period_start: date,
        current_period_end: date,
        next_period_start: date,
        next_period_end: date,
    ) -> JSONResponse:
        view = await compose_weekly_report(
            department, (current_period_start, current_period_end), (next_period_start, next_period_end)
        )
        return JSONResponse(
            status_code=200,
            content={
                "department": view.department,
                "current_week": {
                    "period": {
                        "start": view.current_week.period_start.isoformat(),
                        "end": view.current_week.period_end.isoformat(),
                    },
                    "items": [{"id": item.id, "content": item.content} for item in view.current_week.items],
                },
                "next_week": {
                    "period": {
                        "start": view.next_week.period_start.isoformat(),
                        "end": view.next_week.period_end.isoformat(),
                    },
                    "items": [{"id": item.id, "content": item.content} for item in view.next_week.items],
                },
            },
        )

    @router.get("/report.docx")
    async def get_report_docx(
        department: str,
        current_period_start: date,
        current_period_end: date,
        next_period_start: date,
        next_period_end: date,
    ) -> Response:
        view = await compose_weekly_report(
            department, (current_period_start, current_period_end), (next_period_start, next_period_end)
        )
        docx_bytes = render_weekly_report_docx(view)
        # Content-Disposition 헤더는 latin-1만 허용돼서 한글 파일명을 그대로 못 넣는다.
        # ASCII 대체 파일명 + RFC 6266 filename*(UTF-8 퍼센트 인코딩)을 같이 줘서,
        # 최신 브라우저는 한글 파일명으로, 옛날 클라이언트는 ASCII 이름으로 받게 한다.
        korean_filename = f"주간업무보고_{current_period_start.isoformat()}.docx"
        ascii_fallback = f"weekly-report_{current_period_start.isoformat()}.docx"
        encoded_filename = quote(korean_filename)
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded_filename}'
                )
            },
        )

    @router.get("")
    async def list_entries(
        start: date | None = None,
        end: date | None = None,
        department: str | None = None,
    ) -> JSONResponse:
        async with async_session_factory() as session:
            query = select(WorkReportEntry).order_by(WorkReportEntry.period_start, WorkReportEntry.entry_type)
            if start is not None:
                query = query.where(WorkReportEntry.period_end >= start)
            if end is not None:
                query = query.where(WorkReportEntry.period_start <= end)
            if department is not None:
                query = query.where(WorkReportEntry.department == department)
            result = await session.execute(query)
            entries = result.scalars().all()

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": {
                    "entries": [
                        {
                            "id": entry.id,
                            "department": entry.department,
                            "entry_type": entry.entry_type,
                            "period_start": entry.period_start.isoformat(),
                            "period_end": entry.period_end.isoformat(),
                            "source_category": entry.source_category,
                            "content": entry.content,
                            "source": entry.source,
                        }
                        for entry in entries
                    ],
                },
            },
        )

    @router.patch("/{entry_id}")
    async def update_entry(request: Request, entry_id: str, body: UpdateEntryRequest) -> JSONResponse:
        content = body.content.strip()
        if not content:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {"code": "VALIDATION_ERROR", "message": "내용을 비워둘 수 없습니다."},
                },
            )

        async with async_session_factory() as session:
            entry = await session.get(WorkReportEntry, entry_id)
            if entry is None:
                return JSONResponse(
                    status_code=404,
                    content={
                        "success": False,
                        "error": {"code": "NOT_FOUND", "message": "해당 항목을 찾을 수 없습니다."},
                    },
                )
            entry.content = content
            await session.commit()

            # 검색 인덱스도 최신 내용으로 다시 맞춘다 — 안 하면 검색 결과가 수정 전 문구로 남는다.
            embedding_provider = request.app.state.embedding_provider
            vector_store = request.app.state.vector_store
            await index_entry(session, embedding_provider, vector_store, entry)

        return JSONResponse(
            status_code=200,
            content={"success": True, "data": {"id": entry_id, "content": content}},
        )

    @router.delete("/{entry_id}")
    async def delete_entry(request: Request, entry_id: str) -> JSONResponse:
        async with async_session_factory() as session:
            entry = await session.get(WorkReportEntry, entry_id)
            if entry is None:
                return JSONResponse(
                    status_code=404,
                    content={
                        "success": False,
                        "error": {"code": "NOT_FOUND", "message": "해당 항목을 찾을 수 없습니다."},
                    },
                )
            await session.execute(sa_delete(WorkReportEntry).where(WorkReportEntry.id == entry_id))
            await session.commit()

            vector_store = request.app.state.vector_store
            await deindex_entry(session, vector_store, entry_id)

        return JSONResponse(status_code=200, content={"success": True, "data": {"id": entry_id}})

    return router
