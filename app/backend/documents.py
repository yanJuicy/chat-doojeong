"""문서 업로드 API (app/backend 전용, POST /api/v1/upload + GET /api/v1/documents/{id}).

app/main.py의 기존 POST /api/documents/upload 로직(파일 저장 + DB 등록 + 해시로 중복 검사)을
그대로 재사용하되 두 가지를 더한다:
  1) 응답을 {"success": bool, "data"/"error": ...} 형태의 "봉투(envelope)"로 감싼다.
     프론트가 매번 다른 응답 모양을 기억할 필요 없이 success만 먼저 보면 되게 하려는 목적.
  2) 등록이 끝나자마자 처리(OCR -> 청킹 -> 임베딩)를 백그라운드로 자동 시작한다.
     기존 /api/documents/upload는 "등록"까지만 하고, 실제 처리는 /api/admin/run-workers를
     프론트가 따로 호출해야 했다 — 여기서는 그 호출을 자동으로 대신 해준다.

그리고 프론트가 업로드 직후부터 "지금 몇 단계까지 처리됐는지" 물어볼 수 있는 상태 조회
엔드포인트(GET /api/v1/documents/{id})도 같이 둔다. 업로드 응답의 status는 항상 "uploaded"인데
(아직 OCR 전이라서), 실제로 검색 가능해지는 시점(status == "ready")은 이 엔드포인트를
몇 초 간격으로 폴링해서 확인해야 한다.

코드 안의 분기/흐름을 그림으로 보고 싶으면 documents.md(같은 폴더)에 플로우차트가 있다.
"""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, FastAPI, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select

from ..config import settings
from ..db.models import Document, DocumentLabel, DocumentStatus
from ..db.session import async_session_factory
from ..zip_ingestion import SUPPORTED_EXTENSIONS


def create_documents_router(
    trigger_processing: Callable[[FastAPI], Awaitable[None]],
    upload_dir: Path,
) -> APIRouter:
    """
    trigger_processing: app/main.py의 _run_workers_in_background 함수 (OCR -> 청킹 -> 임베딩 실행).
    upload_dir: app/main.py의 _UPLOAD_DIR (업로드된 원본 파일을 저장할 폴더).

    둘 다 main.py 안에 정의돼 있다. 여기서 main.py를 직접 import하면 "main.py가 이 파일을
    부르고, 이 파일이 다시 main.py를 부르는" 순환 참조 에러가 나기 때문에, main.py 쪽에서
    만들어서 이 함수를 호출할 때 인자로 넘겨받는다.
    """
    router = APIRouter(prefix="/api/v1", tags=["documents"])

    @router.post("/upload")
    async def upload(
        request: Request,
        background_tasks: BackgroundTasks,
        file: UploadFile,
        labels: list[str] = Form(default=[]),
    ) -> JSONResponse:
        # 1단계: 확장자 검사. 지원 목록은 zip 업로드(app/zip_ingestion.py)와 같은 걸 재사용해서
        # 여기저기 확장자 목록이 따로 하드코딩되지 않게 한다.
        safe_filename = Path(file.filename).name
        ext = Path(safe_filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": (
                            f"지원하지 않는 파일 형식입니다: {ext} "
                            f"(지원: {', '.join(sorted(SUPPORTED_EXTENSIONS))})"
                        ),
                    },
                },
            )

        # 2단계: 크기 검사.
        file_bytes = await file.read()
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        if len(file_bytes) > max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": (
                            f"파일이 너무 큽니다 ({len(file_bytes) / 1024 / 1024:.1f}MB > "
                            f"상한 {settings.max_upload_size_mb}MB)"
                        ),
                    },
                },
            )

        # 3단계: 같은 파일(바이트 단위로 완전히 동일)이 이미 업로드돼 있는지 SHA256 해시로 확인.
        # 이미 있으면 새로 등록하지 않고 기존 문서 정보를 그대로 돌려준다.
        file_hash = hashlib.sha256(file_bytes).hexdigest()

        async with async_session_factory() as session:
            existing = await session.execute(select(Document).where(Document.file_hash == file_hash))
            existing_doc = existing.scalars().first()
            if existing_doc is not None:
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "data": {
                            "document_id": existing_doc.id,
                            "filename": existing_doc.filename,
                            "status": existing_doc.status.value,
                            "is_duplicate": True,
                        },
                    },
                )

            # 4단계: 새 문서 - 파일을 디스크에 저장하고, DB에 status=uploaded로 기록한다.
            # labels는 사용자가 "이 문서가 어디의 무엇에 대한 건지" 직접 붙인 태그들이다
            # (예: ["두정테크", "용접방식"]) - 청킹 단계에서 청크 접두어로 쓰인다.
            document_id = str(uuid.uuid4())
            saved_path = upload_dir / f"{document_id}_{safe_filename}"
            saved_path.write_bytes(file_bytes)

            doc = Document(
                id=document_id,
                filename=safe_filename,
                file_path=str(saved_path),
                file_hash=file_hash,
                status=DocumentStatus.UPLOADED,
            )
            session.add(doc)

            unique_labels = {label.strip() for label in labels if label.strip()}
            for label in unique_labels:
                session.add(DocumentLabel(id=str(uuid.uuid4()), document_id=document_id, label=label))

            await session.commit()

        # 5단계: 처리(OCR -> 청킹 -> 임베딩)를 백그라운드로 시작한다.
        # background_tasks.add_task는 "이 함수가 응답을 반환한 뒤에" 실행되므로, 프론트는
        # OCR이 끝날 때까지 기다리지 않고 곧바로 업로드 완료 응답을 받는다. 실제 처리 진행
        # 상황은 아래 GET /api/v1/documents/{id}를 몇 초 간격으로 폴링해서 확인하면 된다.
        background_tasks.add_task(trigger_processing, request.app)

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": {
                    "document_id": document_id,
                    "filename": safe_filename,
                    "status": DocumentStatus.UPLOADED.value,
                    "is_duplicate": False,
                },
            },
        )

    @router.get("/documents/{document_id}")
    async def get_document_status(document_id: str) -> JSONResponse:
        # 프론트는 업로드 응답을 받은 직후부터 이 엔드포인트를 주기적으로 호출해서,
        # status가 "ready"가 될 때까지 "문서 분석 중..." 같은 화면을 보여주면 된다.
        # status 흐름: uploaded -> extracting -> extracted -> chunked -> ready
        #             (품질 미달 시 needs_review로, 실패 시 failed로 빠질 수 있음)
        async with async_session_factory() as session:
            doc = await session.get(Document, document_id)

        if doc is None:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": {"code": "NOT_FOUND", "message": "문서를 찾을 수 없습니다."},
                },
            )

        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "data": {
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "status": doc.status.value,
                    "error_message": doc.error_message,
                    "warning_message": doc.warning_message,
                    "current_page": doc.current_page,
                    "total_pages": doc.total_pages,
                },
            },
        )

    return router
