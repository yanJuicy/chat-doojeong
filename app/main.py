"""
FastAPI 엔트리포인트 — DB 중심(DB-centric) 아키텍처.

핵심 설계: 업로드 엔드포인트는 "파일을 저장하고 DB에 상태를 기록"하는 것까지만 책임진다.
OCR/청킹/임베딩은 각각 app/workers/*.py의 독립된 워커가 담당하고, 서로 직접 호출하지 않는다.
각 워커는 오직 Document.status(DB)만 보고 다음 처리할 대상을 찾는다.

그래서:
  - OCR 엔진을 교체하고 싶으면 app/workers/extraction_worker.py 안의 구현체 선택만 바꾸면 된다.
    이 파일(main.py)이나 청킹/임베딩 워커는 전혀 건드릴 필요가 없다.
  - 워커들은 이 FastAPI 프로세스 안에서 백그라운드로 돌 수도 있고(지금 /api/admin/run-workers처럼),
    완전히 별도 프로세스/컨테이너로 떼어내서 `python -m app.workers.extraction_worker`로 실행할 수도 있다.
    DB만 공유하면 되므로 이 결합도 낮은 구조 자체가 "밖으로 빼서 집어넣는" 요구사항을 만족한다.

흐름:
  POST /api/documents/upload          -> 파일 저장 + Document(status=UPLOADED) 생성만 함 (OCR 호출 없음)
  POST /api/admin/run-workers         -> extraction -> chunking -> embedding 워커를 순서대로 1회 실행 (개발/테스트 편의용)
  POST /api/chat                      -> 검색 -> 리랭킹 -> LLM 답변 생성 (기존과 동일, 이 부분은 OCR과 무관해서 안 건드림)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langdetect import detect as detect_language
from collections import defaultdict
from sqlalchemy import delete, func, select

from .api_models import (
    ChatImage,
    ChatRequest,
    ChatResponse,
    ChatSource,
    CrawlRequest,
    CrawlResponse,

    DeleteDocumentIssue,
    DeleteDocumentsRequest,
    DeleteDocumentsResponse,
    DedupeDocumentsResponse,
    DuplicateGroupInfo,
    RunWorkersResponse,

    RunWorkersAcceptedResponse,

    UpdateLabelsRequest,
    UploadResponse,
    ZipUploadItem,
    ZipUploadResponse,
)
from .backend.chat_stream import create_chat_stream_router
from .backend.documents import create_documents_router
from .backend.work_reports import create_work_reports_router
from .config import settings
from .core.bge_m3_provider import BgeM3EmbeddingProvider
from .core.bge_reranker import BgeRerankerV2
from .core.extractor_registry import ExtractorRegistry
from .core.intent_classifier import IntentClassifier
from .core.label_matching import expand_search_query
from .core.qdrant_store import QdrantVectorStore
from .core.qwen_ollama_provider import QwenOllamaProvider, build_cross_lingual_system_prompt
from .core.question_cache import SemanticQuestionCache, build_query_signature
from .core.retrieval_pipeline import rerank_candidates, retrieve_candidates
from .core.answer_prompt import build_grounded_answer_prompt, build_grounded_system_prompt
from .core.structured_chunker import StructuredChunker
from .core.similarity_utils import cosine_similarity
from .core.work_report_indexing import deindex_entry
from .db.models import (
    ChatLog,
    Document,
    DocumentChunk,
    DocumentLabel,
    DocumentStatus,
    WorkReportDocument,
    WorkReportEntry,
)
from .db.session import async_session_factory
from .report_api import create_shipment_report_router
from .routers.evaluation import create_evaluation_router
from .workers import chunking_worker, embedding_worker, extraction_worker
from .zip_ingestion import process_zip_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_UPLOAD_DIR = Path("./uploaded_files")

# 답변 텍스트에 실제로 인용된 "[참고 N]" 번호를 뽑는다. context_blocks가 1부터 순서대로
# [참고 1], [참고 2] ...로 reranked와 1:1 대응하므로, 이 번호로 reranked[N-1]을 찾을 수 있다.
_CITED_REFERENCE_PATTERN = re.compile(r"\[참고\s*(\d+)\]")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """무거운 모델/클라이언트는 앱 시작 시 한 번만 로딩해서 app.state에 보관한다."""
    logger.info("서비스 컴포넌트 초기화 시작")

    # DB 스키마는 이제 Alembic이 관리한다 (`alembic upgrade head`).
    # 예전엔 여기서 create_all()을 불렀는데, 그건 "테이블이 아예 없을 때"만 만들어주고
    # 이미 있는 테이블에 컬럼을 추가하는 건 못 해서, 컬럼 추가할 때마다 수동으로 ALTER TABLE을
    # 쳐야 했다. 지금은 서버가 알아서 고치는 대신, 마이그레이션이 안 됐으면 명확히 알려준다.
    logger.info("DB 스키마는 Alembic이 관리합니다 — 처음 세팅이거나 최근에 컬럼을 추가했다면 `alembic upgrade head`를 먼저 실행하세요.")

    embedding_provider = BgeM3EmbeddingProvider()
    reranker = BgeRerankerV2()
    vector_store = QdrantVectorStore()
    await vector_store.ensure_collection()
    llm_provider = QwenOllamaProvider()
    chunker = StructuredChunker(embedding_provider=embedding_provider)

    app.state.embedding_provider = embedding_provider
    app.state.label_embedding_cache = {}  # 문서 라벨 자동완성용 임베딩 캐시 (라벨 텍스트 -> 벡터)
    app.state.reranker = reranker
    app.state.vector_store = vector_store
    app.state.llm_provider = llm_provider
    app.state.chunker = chunker
    app.state.intent_classifier = IntentClassifier(embedding_provider=embedding_provider)
    app.state.question_cache = SemanticQuestionCache(
        max_size=settings.question_cache_max_size,
        ttl=timedelta(hours=settings.question_cache_ttl_hours),
        similarity_threshold=settings.question_cache_similarity_threshold,
    )
    # PaddleOCR은 로딩이 무겁고 안 쓰는 배포도 있으므로, extraction_worker 실행 시점에 지연 로딩한다.
    app.state.extractor_registry = ExtractorRegistry()
    # DB의 SKIP LOCKED는 중복 선점만 막으므로, GPU를 만지는 모든 경로(백그라운드 워커 + /api/chat)를
    # 이 잠금 하나로 직렬화한다. 안 그러면 채팅 중 임베딩/청킹 배치가 동시에 GPU를 잡아
    # VRAM이 부족한 카드(RTX 5060 8GB 등)에서 OOM이 날 수 있다.
    app.state.gpu_lock = asyncio.Lock()

    _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("서비스 컴포넌트 초기화 완료")
    yield
    logger.info("서비스 종료")


app = FastAPI(title="온프레미스 RAG 챗봇 서버 (DB 중심 아키텍처)", lifespan=lifespan)

# React 개발 서버(CRA 3000 / Vite 5173) 로컬 접속 허용. 배포 시 실제 프론트 도메인으로 좁혀야 한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).parent / "static"
_FRONTEND_DIST_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"
_FRONTEND_ASSETS_DIR = _FRONTEND_DIST_DIR / "assets"

if _FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_ASSETS_DIR), name="frontend-assets")


async def _get_available_document_labels() -> list[str]:
    """현재 라벨을 조회해 질문의 명시적 회사·제품 힌트를 판별한다."""
    async with async_session_factory() as session:
        result = await session.execute(select(DocumentLabel.label).distinct())
        return [label for (label,) in result.all() if label]


Path(settings.image_storage_dir).mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=settings.image_storage_dir), name="images")


@app.get("/", response_class=HTMLResponse)
async def serve_console():
    """빌드된 React 화면을 제공하고, 빌드가 없을 때만 기존 개발용 콘솔로 대체한다."""
    react_index = _FRONTEND_DIST_DIR / "index.html"
    if react_index.exists():
        return FileResponse(react_index)
    return (_STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/api/documents/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile, labels: list[str] = Form(default=[])) -> UploadResponse:
    """
    파일을 저장하고 DB에 status=UPLOADED로 기록만 한다.
    OCR/청킹/임베딩은 여기서 호출하지 않는다 (워커가 DB를 보고 알아서 처리).
    동일 파일(바이트 단위 완전 일치)이 이미 있으면 새로 등록하지 않고 안내만 한다.

    labels: "어디의 무엇에 대한 문서인지" 사용자가 직접 지정하는 라벨들 (예: ["두정테크", "용접방식"]).
    한 문서가 여러 라벨을 동시에 가질 수 있다 (회사명+주제 등). 파일명이 내용을 잘 대표 못 하는
    경우(스캔 파일명 등)를 위해, 청킹 시 이 값들을 청크 접두어로 쓴다 (하나도 없으면 파일명으로 대체).
    """
    safe_filename = Path(file.filename).name
    ext = Path(safe_filename).suffix.lower()
    if ext not in (".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".jpg", ".jpeg", ".png"):
        raise HTTPException(
            status_code=400, detail=f"지원하지 않는 파일 형식입니다: {ext} (지원: .pdf, .docx, .txt, .md, .html, .jpg, .png)"
        )

    file_bytes = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413, detail=f"파일이 너무 큽니다 ({len(file_bytes) / 1024 / 1024:.1f}MB > 상한 {settings.max_upload_size_mb}MB)"
        )
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    async with async_session_factory() as session:
        existing = await session.execute(select(Document).where(Document.file_hash == file_hash))
        existing_doc = existing.scalars().first()
        if existing_doc is not None:
            logger.info("중복 파일 업로드 감지: 기존 document_id=%s와 해시 일치", existing_doc.id)
            return UploadResponse(
                document_id=existing_doc.id,
                status=existing_doc.status.value,
                is_duplicate=True,
            )

        document_id = str(uuid.uuid4())
        saved_path = _UPLOAD_DIR / f"{document_id}_{safe_filename}"
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

    logger.info("문서 업로드 완료 (OCR 대기 중): document_id=%s", document_id)
    return UploadResponse(document_id=document_id, status=DocumentStatus.UPLOADED.value)


@app.post("/api/documents/upload-zip", response_model=ZipUploadResponse)
async def upload_zip(file: UploadFile) -> ZipUploadResponse:
    """
    zip 파일 하나를 받아 안의 PDF/Word/텍스트/HTML을 전부 찾아 자동으로 업로드 등록한다.
    안에 zip이 또 있으면(중첩 압축) 재귀적으로 풀어서 그 안의 파일들도 찾아낸다.
    (압축 안의 폴더 구조는 무시하고 파일명만 사용, 지원 안 하는 확장자는 건너뛰고 skipped에 표시)
    """
    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="zip 파일만 업로드 가능합니다.")

    zip_bytes = await file.read()
    max_zip_bytes = settings.max_zip_total_uncompressed_mb * 1024 * 1024
    if len(zip_bytes) > max_zip_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"zip 파일이 너무 큽니다 ({len(zip_bytes) / 1024 / 1024:.1f}MB > 상한 {settings.max_zip_total_uncompressed_mb}MB)",
        )

    created: list[ZipUploadItem] = []
    skipped: list[str] = []
    await process_zip_bytes(zip_bytes, _UPLOAD_DIR, created, skipped)

    logger.info("zip 업로드 완료: %d개 등록, %d개 건너뜀", len(created), len(skipped))
    return ZipUploadResponse(created=created, skipped=skipped)


@app.post("/api/documents/crawl", response_model=CrawlResponse)
async def crawl_website(body: CrawlRequest) -> CrawlResponse:
    """
    seed_url부터 같은 도메인 안에서 링크를 따라가며 페이지를 수집해 DB에 등록한다 (status=UPLOADED).
    주의: 실제 외부 인터넷 접속이 필요하다 — 폐쇄망 서버에서는 호출하면 안 되고,
    인터넷이 되는 별도 환경에서 실행해서 결과를 반입하는 용도로 쓴다.
    텍스트 추출(HtmlExtractor)은 여기서 하지 않는다 — extraction_worker가 나중에 처리한다.
    """
    from .services.web_crawler.crawler import crawl

    crawl_output_dir = _UPLOAD_DIR / "crawled_html"

    # requests 기반 동기 크롤링이라 이벤트 루프를 막지 않도록 별도 스레드에서 실행한다.
    results = await asyncio.to_thread(
        crawl,
        seed_url=body.seed_url,
        allowed_domain=body.allowed_domain,
        output_dir=str(crawl_output_dir),
        max_pages=body.max_pages,
        max_depth=body.max_depth,
    )

    document_ids: list[str] = []
    async with async_session_factory() as session:
        for result in results:
            document_id = str(uuid.uuid4())
            doc = Document(
                id=document_id,
                filename=result.title or result.url,
                file_path=result.html_path,
                status=DocumentStatus.UPLOADED,
            )
            session.add(doc)
            document_ids.append(document_id)
        await session.commit()

    logger.info("크롤링 완료: %d개 페이지 -> DB 등록 (OCR/추출 대기 중)", len(results))
    return CrawlResponse(n_pages_crawled=len(results), document_ids=document_ids)


@app.post("/api/documents/ingest-text", response_model=UploadResponse)
async def ingest_text_document(document_id: str, filename: str, text: str) -> UploadResponse:
    """
    이미 텍스트로 추출된 문서를 곧바로 EXTRACTED 상태로 등록한다 (OCR 단계 생략).
    표 마커(<!-- TABLE_BLOCK_START/END -->)가 포함된 텍스트를 그대로 넣으면 된다.
    """
    async with async_session_factory() as session:
        doc = Document(
            id=document_id,
            filename=filename,
            status=DocumentStatus.EXTRACTED,
            raw_text=text,
        )
        session.add(doc)
        await session.commit()

    return UploadResponse(document_id=document_id, status=DocumentStatus.EXTRACTED.value)


@app.post("/api/admin/run-workers", response_model=RunWorkersAcceptedResponse)
async def run_workers(request: Request, background_tasks: BackgroundTasks) -> RunWorkersAcceptedResponse:
    """
    extraction -> chunking -> embedding 워커를 순서대로 실행한다.
    OCR이 몇 분~몇십 분 걸릴 수 있어서, 이 요청 자체는 백그라운드에 맡기고 즉시 응답한다
    (그래야 브라우저가 그동안 멈춘 것처럼 안 보이고, 콘솔의 상태 폴링으로 진행률을 실시간으로 볼 수 있다).
    """
    background_tasks.add_task(_run_workers_in_background, request.app)
    return RunWorkersAcceptedResponse(status="started")

@app.post("/api/admin/dedupe-documents", response_model=DedupeDocumentsResponse)
async def dedupe_documents(request: Request, apply: bool = False) -> DedupeDocumentsResponse:
    """
    같은 filename + raw_text가 글자 하나까지 완전히 동일한 문서들을 찾아,
    가장 먼저 인덱싱된 것 하나만 남기고 나머지를 정리한다.
    apply=false(기본값)면 미리보기만 하고 실제로는 아무것도 지우지 않는다.
    """
    async with async_session_factory() as session:
        result = await session.execute(select(Document))
        docs = list(result.scalars().all())

    candidates: dict[tuple[str, int], list[Document]] = defaultdict(list)
    for d in docs:
        if d.raw_text:
            candidates[(d.filename, len(d.raw_text))].append(d)

    duplicate_groups: list[list[Document]] = []
    for group in candidates.values():
        if len(group) < 2:
            continue
        by_text: dict[str, list[Document]] = defaultdict(list)
        for d in group:
            by_text[d.raw_text].append(d)
        for dupes in by_text.values():
            if len(dupes) >= 2:
                duplicate_groups.append(sorted(dupes, key=lambda x: x.created_at))

    groups_info: list[DuplicateGroupInfo] = []
    documents_removed = 0

    if apply:
        vector_store: QdrantVectorStore = request.app.state.vector_store
        async with async_session_factory() as session:
            for group in duplicate_groups:
                keep, *remove = group
                groups_info.append(
                    DuplicateGroupInfo(
                        filename=keep.filename,
                        kept_document_id=keep.id,
                        removed_document_ids=[d.id for d in remove],
                    )
                )
                for d in remove:
                    chunks_result = await session.execute(
                        select(DocumentChunk).where(DocumentChunk.document_id == d.id)
                    )
                    for chunk in chunks_result.scalars().all():
                        await session.delete(chunk)
                    await session.delete(d)
                    await session.commit()
                    await vector_store.delete_by_document_id(d.id)
                    documents_removed += 1
    else:
        for group in duplicate_groups:
            keep, *remove = group
            groups_info.append(
                DuplicateGroupInfo(
                    filename=keep.filename,
                    kept_document_id=keep.id,
                    removed_document_ids=[d.id for d in remove],
                )
            )
            documents_removed += len(remove)

    return DedupeDocumentsResponse(
        applied=apply,
        groups_found=len(duplicate_groups),
        documents_removed=documents_removed,
        groups=groups_info,
    )


async def _run_workers_in_background(app: FastAPI) -> None:
    """run_workers의 실제 처리부. 응답을 이미 보낸 뒤 백그라운드에서 실행된다."""
    gpu_lock = getattr(app.state, "gpu_lock", None)
    if gpu_lock is None:
        gpu_lock = asyncio.Lock()
        app.state.gpu_lock = gpu_lock

    # 겹친 요청을 버리지 않고 직렬화한다. 앞선 실행이 끝나는 순간 새 문서가 들어와도
    # 대기 중인 실행이 DB를 한 번 더 확인하므로 작업이 남겨지는 경쟁 조건을 피한다.
    # 이 잠금은 /api/chat의 GPU 사용 구간과도 공유되므로, 채팅 응답 생성 중에는
    # 백그라운드 워커의 다음 배치가 대기한다 (그 반대도 마찬가지).
    async with gpu_lock:
        try:
            n_extracted = 0
            n_chunked = 0
            n_embedded = 0
            round_number = 0
            claim_size = max(1, settings.worker_claim_batch_size)
            batches_per_round = max(
                1,
                (settings.pipeline_round_document_limit + claim_size - 1) // claim_size,
            )

            while True:
                round_number += 1
                round_extracted = 0
                for _ in range(batches_per_round):
                    batch_count = await extraction_worker.process_pending_documents(
                        async_session_factory, app.state.extractor_registry
                    )
                    round_extracted += batch_count
                    if batch_count == 0:
                        break

                round_chunked = 0
                for _ in range(batches_per_round):
                    async with async_session_factory() as session:
                        batch_count = await chunking_worker.process_pending_documents(
                            session,
                            app.state.chunker,
                            app.state.embedding_provider,
                            app.state.llm_provider,
                        )
                    round_chunked += batch_count
                    if batch_count == 0:
                        break

                # 최대 16개 문서의 라벨 생성을 마친 뒤 한 번만 Qwen을 내린다.
                # 작은 배치마다 모델을 재로딩하지 않으면서 먼저 끝난 문서는 임베딩으로 넘긴다.
                if round_chunked > 0:
                    await app.state.llm_provider.unload()

                round_embedded = 0
                while True:
                    async with async_session_factory() as session:
                        batch_count = await embedding_worker.process_pending_chunks(
                            session, app.state.embedding_provider, app.state.vector_store
                        )
                    round_embedded += batch_count
                    if batch_count == 0:
                        break

                n_extracted += round_extracted
                n_chunked += round_chunked
                n_embedded += round_embedded
                logger.info(
                    "파이프라인 순환 %d 완료: 추출 %d, 청킹 %d, 임베딩 %d",
                    round_number,
                    round_extracted,
                    round_chunked,
                    round_embedded,
                )

                if round_extracted == 0 and round_chunked == 0 and round_embedded == 0:
                    break

            logger.info(
                "백그라운드 워커 실행 완료: 추출 %d, 청킹 %d, 임베딩 %d",
                n_extracted,
                n_chunked,
                n_embedded,
            )
        except Exception as exc:
            # 백그라운드 태스크 안 예외는 어디에도 안 알려지고 조용히 사라지므로, 반드시 여기서 로그를 남긴다.
            logger.error("백그라운드 워커 실행 중 예외 발생: %s", exc, exc_info=True)


@app.get("/api/documents/{document_id}/file")
async def get_document_file(document_id: str):
    """업로드된 원본 파일을 그대로 반환한다 (콘솔에서 문서를 클릭해 바로 열어볼 수 있게)."""
    from fastapi.responses import FileResponse

    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None or not doc.file_path:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

        file_path = Path(doc.file_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="원본 파일이 디스크에 없습니다 (삭제되었거나 이동됨).")

        return FileResponse(path=file_path, filename=doc.filename, content_disposition_type="inline")


@app.get("/api/documents/{document_id}/status")
async def get_document_status(document_id: str) -> dict:
    """문서가 파이프라인의 어느 단계까지 갔는지 조회한다 (디버깅용)."""
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
        return {
            "document_id": doc.id,
            "filename": doc.filename,
            "status": doc.status.value,
            "error_message": doc.error_message,
            "warning_message": doc.warning_message,
            "retry_count": doc.retry_count,
            "current_page": doc.current_page,
            "total_pages": doc.total_pages,
            "extraction_quality_score": doc.extraction_quality_score,
            "extraction_quality_details": (
                json.loads(doc.extraction_quality_details) if doc.extraction_quality_details else None
            ),
            "extraction_method": doc.extraction_method,
            "pipeline_version": doc.pipeline_version,
            "indexed_at": doc.indexed_at,
        }


@app.get("/api/documents/{document_id}/labels")
async def get_document_labels(document_id: str) -> list[str]:
    """문서 하나에 지금 붙어있는 라벨 목록을 조회한다 (수정 UI에서 현재값 채워넣을 때 사용)."""
    async with async_session_factory() as session:
        result = await session.execute(select(DocumentLabel.label).where(DocumentLabel.document_id == document_id))
        return [row[0] for row in result.all()]


@app.put("/api/documents/{document_id}/labels")
async def update_document_labels(document_id: str, body: UpdateLabelsRequest, background_tasks: BackgroundTasks, request: Request) -> dict:
    """
    문서의 라벨을 통째로 교체하고, 새 라벨이 실제로 검색에 반영되도록 자동으로 재처리한다.

    라벨이 바뀌면 청크 텍스트(접두어 "[문서: ...]")도 달라져야 하므로, 옛 청크와 옛 벡터를
    지우고 문서를 청킹 전 상태로 되돌린 뒤 백그라운드로 워커를 돌린다 — 저장 버튼 한 번으로
    끝나게 만드는 게 목적이라, 별도로 "재처리 시작" 버튼을 또 누르지 않아도 된다.
    """
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

        # 동일 라벨로 재청킹할 때 ORM이 INSERT를 DELETE보다 먼저 보내면 고유키 충돌이 날 수 있다.
        # 명시적인 bulk DELETE를 먼저 실행하면 순서가 보장되고, 수천 청크 문서도 행을 하나씩
        # 메모리에 올려 삭제하지 않아 훨씬 빠르다.
        await session.execute(delete(DocumentLabel).where(DocumentLabel.document_id == document_id))
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))

        unique_labels = sorted({label.strip() for label in body.labels if label.strip()})
        for label in unique_labels:
            session.add(DocumentLabel(id=str(uuid.uuid4()), document_id=document_id, label=label))

        # OCR까지 다시 할 필요는 없다 (원문은 그대로) - 청킹부터 다시 하면 된다.
        doc.status = DocumentStatus.EXTRACTED if doc.raw_text else DocumentStatus.UPLOADED
        doc.indexed_at = None
        doc.current_page = None
        doc.total_pages = None
        doc.retry_count = 0
        doc.error_message = None

        await session.commit()

    invalidated = request.app.state.question_cache.invalidate_document(document_id)
    if invalidated:
        logger.info("문서 변경으로 질문 캐시 %d건 무효화: document_id=%s", invalidated, document_id)

    # 벡터DB에 남은 옛 벡터도 지운다 (안 지우면 새 청크와 옛 청크가 같이 검색됨).
    await request.app.state.vector_store.delete_by_document_id(document_id)

    background_tasks.add_task(_run_workers_in_background, request.app)

    logger.info("문서 라벨 수정 및 재처리 시작: document_id=%s, labels=%s", document_id, unique_labels)
    return {"document_id": document_id, "labels": unique_labels, "status": "reprocessing"}


@app.post("/api/documents/{document_id}/retry")
async def retry_document(document_id: str) -> dict:
    """
    실패했거나 멈춰있는 문서를 다시 처리 대상에 올린다 (자동 재시도 상한을 넘겼을 때, 또는
    워커 프로세스가 죽거나 멈춰서 특정 상태에 계속 머물러 있을 때 수동으로 쓰는 용도).

    - status=FAILED면: raw_text가 이미 있으면 청킹부터(EXTRACTED로), 없으면 추출부터(UPLOADED로) 다시 돌게 되돌리고
      retry_count를 리셋한다.
    - status=EXTRACTING인데 멈춰있으면(워커가 특정 페이지 처리 중 죽거나 응답 없음): UPLOADED로 되돌려서
      다시 찜해서 재시도되게 한다. 이미 처리된 페이지는 OCR 캐시가 있어서 재시도가 훨씬 빠르다.
    - status=CHUNKED인데 일부 청크가 임베딩 재시도 상한을 넘어 계속 제외되고 있으면, 그 청크들의
      embed_retry_count도 같이 리셋해서 다음 워커 실행 때 다시 시도되게 한다.
    """
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")

        if doc.status == DocumentStatus.NEEDS_REVIEW:
            doc.status = DocumentStatus.UPLOADED
            doc.indexed_at = None
            doc.retry_count = 0
            doc.error_message = None
            doc.warning_message = "[수동 재시도] OCR 품질 검토 문서를 다시 추출합니다."
            logger.info("수동 재시도(추출 품질): document_id=%s -> uploaded", document_id)
        elif doc.status == DocumentStatus.FAILED:
            doc.status = DocumentStatus.EXTRACTED if doc.raw_text else DocumentStatus.UPLOADED
            doc.indexed_at = None
            doc.retry_count = 0
            doc.error_message = None
            logger.info("수동 재시도: document_id=%s -> status=%s로 되돌림", document_id, doc.status.value)
        elif doc.status == DocumentStatus.EXTRACTING:
            # 워커가 이 문서를 처리하던 도중 죽었거나 멈춘 것으로 보고, 다시 찜할 수 있는 상태로 되돌린다.
            doc.status = DocumentStatus.UPLOADED
            doc.current_page = None
            doc.total_pages = None
            doc.error_message = "[수동 재시도] extracting 상태에서 멈춰있어 처음부터 다시 시도합니다 (완료된 페이지는 OCR 캐시로 빠르게 넘어갑니다)."
            logger.info("수동 재시도(멈춘 추출): document_id=%s -> uploaded로 되돌림", document_id)

        stuck_result = await session.execute(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.embed_retry_count >= settings.worker_max_retries,
            )
        )
        stuck_chunks = list(stuck_result.scalars().all())
        for chunk in stuck_chunks:
            chunk.embed_retry_count = 0

        await session.commit()
        return {"document_id": document_id, "status": doc.status.value, "reset_stuck_chunks": len(stuck_chunks)}


@app.post("/api/documents/{document_id}/reextract")
async def reextract_document(
    document_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """라벨과 원본 파일은 보존하고, 잘못된 OCR·청크·벡터만 버린 뒤 추출부터 다시 시작한다."""
    async with async_session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
        if not doc.file_path or not Path(doc.file_path).exists():
            raise HTTPException(status_code=409, detail="원본 파일이 없어 다시 추출할 수 없습니다.")

        chunks_result = await session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        for chunk in chunks_result.scalars().all():
            await session.delete(chunk)

        doc.raw_text = None
        doc.status = DocumentStatus.UPLOADED
        doc.current_page = None
        doc.total_pages = None
        doc.extraction_quality_score = None
        doc.extraction_quality_details = None
        doc.extraction_method = None
        doc.pipeline_version = None
        doc.indexed_at = None
        doc.retry_count = 0
        doc.error_message = None
        doc.warning_message = None
        await session.commit()

    invalidated = request.app.state.question_cache.invalidate_document(document_id)
    if invalidated:
        logger.info("문서 변경으로 질문 캐시 %d건 무효화: document_id=%s", invalidated, document_id)

    # DB가 먼저 UPLOADED가 되었기 때문에 Qdrant 삭제가 잠시 실패해도 검색 단계의 READY 필터가
    # 옛 포인트를 노출하지 않는다. 삭제 성공 뒤에만 새 워커를 시작한다.
    await request.app.state.vector_store.delete_by_document_id(document_id)
    background_tasks.add_task(_run_workers_in_background, request.app)
    logger.info("문서 원문 재추출 시작: document_id=%s", document_id)
    return {"document_id": document_id, "status": "reextracting"}


@app.get("/api/document-labels/search")
async def search_document_labels(q: str, request: Request) -> list[str]:
    """
    지금까지 사용자가 입력했던 라벨 중, q와 의미가 가까운 것들을 유사도순으로 반환한다
    (자동완성용). 별도 카테고리 테이블을 안 두고, 실제 쓰인 라벨들 자체가 목록이 되게 해서
    새 회사/제품군이 추가될 때마다 코드/스키마를 안 건드려도 자동으로 자동완성에 들어온다.

    글자 일치가 아니라 임베딩 유사도로 찾는다 -- "케이디은행"이라고 쳐도 기존에 "KD은행"이
    있으면 후보로 뜬다 (표기만 다르고 같은 대상인 경우를 잡아내려는 목적). q가 비어있으면
    최근 사용순으로 보여준다(이건 의미 비교가 필요 없어서 가볍게 처리).
    """
    if not q.strip():
        async with async_session_factory() as session:
            stmt = (
                select(DocumentLabel.label, func.max(DocumentLabel.created_at))
                .group_by(DocumentLabel.label)
                .order_by(func.max(DocumentLabel.created_at).desc())
                .limit(8)
            )
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    async with async_session_factory() as session:
        result = await session.execute(select(DocumentLabel.label).distinct())
        all_labels = [row[0] for row in result.all()]
    if not all_labels:
        return []

    embedding_provider = request.app.state.embedding_provider
    label_cache: dict = request.app.state.label_embedding_cache

    # 라벨 개수는 회사/제품군 수만큼이라 문서 수보다 훨씬 적고, 한 번 임베딩한 라벨은 캐시해서
    # 같은 라벨을 다시 임베딩하는 낭비를 없앤다 (새 라벨이 추가될 때만 그만큼만 새로 계산).
    missing = [label for label in all_labels if label not in label_cache]
    if missing:
        vectors = await embedding_provider.embed_documents(missing)
        for label, vector in zip(missing, vectors):
            label_cache[label] = vector

    query_vec = await embedding_provider.embed_query(q.strip())
    scored = [(label, cosine_similarity(query_vec, label_cache[label])) for label in all_labels]
    scored.sort(key=lambda item: item[1], reverse=True)
    return [label for label, _ in scored[:8]]


@app.get("/api/documents/needs-review")
async def list_documents_needing_review() -> list[dict]:
    """청킹 품질 경고(warning_message)가 있는 문서 목록을 조회한다 (사람이 골라서 재검토할 대상)."""
    async with async_session_factory() as session:
        result = await session.execute(select(Document).where(Document.warning_message.is_not(None)))
        docs = result.scalars().all()
        return [
            {
                "document_id": d.id,
                "filename": d.filename,
                "status": d.status.value,
                "warning_message": d.warning_message,
                "extraction_quality_score": d.extraction_quality_score,
                "extraction_method": d.extraction_method,
            }
            for d in docs
        ]


@app.get("/api/documents")
async def list_documents() -> list[dict]:
    """업로드된 문서 전체 목록을 조회한다 (콘솔 UI에서 문서 선택용, 새로고침해도 이력이 남도록).

    주간보고서 항목을 검색에 연결하려고 항목 하나당 만든 내부용 Document(라벨
    "주간보고서"로 표시됨, work_report_indexing.py 참고)는 여기서 제외한다 —
    실제 업로드한 파일이 아니라 검색용 조각이라 그대로 노출하면 목록이 항목 개수만큼
    불어난다. 대신 주간보고서로 업로드된 원본 PDF(work_report_documents)를 같은
    모양으로 변환해서 끼워 넣는다 — 사용자 입장에선 "내가 업로드한 파일"이 하나로
    보이는 게 자연스럽다.
    """
    async with async_session_factory() as session:
        work_report_marker_ids = (
            select(DocumentLabel.document_id).where(DocumentLabel.label == "주간보고서")
        ).scalar_subquery()
        result = await session.execute(
            select(Document)
            .where(Document.id.notin_(work_report_marker_ids))
            .order_by(Document.created_at.desc())
        )
        docs = result.scalars().all()

        labels_result = await session.execute(select(DocumentLabel.document_id, DocumentLabel.label))
        labels_by_doc: dict[str, list[str]] = {}
        for document_id, label in labels_result.all():
            labels_by_doc.setdefault(document_id, []).append(label)

        work_report_docs_result = await session.execute(
            select(WorkReportDocument).order_by(WorkReportDocument.uploaded_at.desc())
        )
        work_report_docs = work_report_docs_result.scalars().all()

        combined = [
            {
                "document_id": d.id,
                "filename": d.filename,
                "status": d.status.value,
                "current_page": d.current_page,
                "total_pages": d.total_pages,
                "retry_count": d.retry_count,
                "error_message": d.error_message,
                "warning_message": d.warning_message,
                "extraction_quality_score": d.extraction_quality_score,
                "extraction_method": d.extraction_method,
                "created_at": d.created_at,
                "updated_at": d.updated_at,
                "indexed_at": d.indexed_at,
                "labels": labels_by_doc.get(d.id, []),
            }
            for d in docs
        ] + [
            {
                "document_id": w.id,
                "filename": w.filename,
                "status": "ready",
                "current_page": None,
                "total_pages": w.pages_with_table + w.pages_without_table,
                "retry_count": 0,
                "error_message": None,
                "warning_message": (
                    f"{w.pages_without_table}개 페이지에서 표를 인식하지 못함"
                    if w.pages_without_table
                    else None
                ),
                "extraction_quality_score": None,
                "extraction_method": "work_report_table_parser",
                "created_at": w.uploaded_at,
                "updated_at": w.uploaded_at,
                "indexed_at": w.uploaded_at,
                "labels": ["주간보고서"] + ([w.department] if w.department else []),
            }
            for w in work_report_docs
        ]
        combined.sort(key=lambda item: item["created_at"], reverse=True)
        return combined


_DELETE_BLOCKED_STATUSES = {
    DocumentStatus.EXTRACTING,
    DocumentStatus.EXTRACTED,
    DocumentStatus.CHUNKED,
}


def _unlink_managed_file(path: Path, root: Path, warnings: list[str]) -> None:
    """관리 디렉터리 안의 파일만 삭제한다. 경로가 밖을 가리키면 안전을 위해 건너뛴다."""
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        resolved_path.relative_to(resolved_root)
        if resolved_path.is_file():
            resolved_path.unlink()
    except (OSError, ValueError) as exc:
        warnings.append(f"{path}: {exc}")


async def _delete_documents(
    request: Request,
    document_ids: list[str],
) -> DeleteDocumentsResponse:
    unique_ids = list(dict.fromkeys(document_ids))
    response = DeleteDocumentsResponse()
    source_paths: list[Path] = []
    image_paths: list[Path] = []

    async with async_session_factory() as session:
        result = await session.execute(
            select(Document)
            .where(Document.id.in_(unique_ids))
            .with_for_update()
        )
        documents = {document.id: document for document in result.scalars().all()}
        response.missing = [document_id for document_id in unique_ids if document_id not in documents]

        # documents 테이블엔 없지만(주간보고서 업로드 원본은 별도 테이블이라 여기 안 잡힘)
        # work_report_documents에 있는 id는 여기서 같이 처리하고 missing에서 뺀다.
        if response.missing:
            wrd_result = await session.execute(
                select(WorkReportDocument).where(WorkReportDocument.id.in_(response.missing))
            )
            work_report_docs = {w.id: w for w in wrd_result.scalars().all()}
            if work_report_docs:
                response.missing = [
                    document_id for document_id in response.missing if document_id not in work_report_docs
                ]
                for wrd in work_report_docs.values():
                    entry_result = await session.execute(
                        select(WorkReportEntry.id).where(WorkReportEntry.source_document_id == wrd.id)
                    )
                    entry_ids = [row[0] for row in entry_result.all()]
                    for entry_id in entry_ids:
                        await deindex_entry(session, request.app.state.vector_store, entry_id)
                    if entry_ids:
                        await session.execute(delete(WorkReportEntry).where(WorkReportEntry.id.in_(entry_ids)))
                    await session.execute(delete(WorkReportDocument).where(WorkReportDocument.id == wrd.id))
                    await session.commit()
                    _unlink_managed_file(Path(wrd.file_path), _UPLOAD_DIR.resolve(), response.cleanup_warnings)
                    response.deleted.append(wrd.id)

        deletable: list[Document] = []
        for document_id in unique_ids:
            document = documents.get(document_id)
            if document is None:
                continue
            if document.status in _DELETE_BLOCKED_STATUSES:
                response.blocked.append(
                    DeleteDocumentIssue(
                        document_id=document.id,
                        reason="현재 문서 처리 중입니다. 처리가 끝난 뒤 삭제해 주세요.",
                    )
                )
                continue
            try:
                await request.app.state.vector_store.delete_by_document_id(document.id)
            except Exception as exc:  # noqa: BLE001
                logger.error("문서 삭제 전 Qdrant 정리 실패: document_id=%s", document.id, exc_info=True)
                response.blocked.append(
                    DeleteDocumentIssue(
                        document_id=document.id,
                        reason=f"벡터 데이터 정리에 실패했습니다: {exc}",
                    )
                )
                continue
            deletable.append(document)

        deletable_ids = [document.id for document in deletable]
        if deletable_ids:
            chunk_result = await session.execute(
                select(DocumentChunk.image_path).where(
                    DocumentChunk.document_id.in_(deletable_ids),
                    DocumentChunk.image_path.is_not(None),
                )
            )
            image_root = Path(settings.image_storage_dir)
            image_paths = [image_root / Path(image_path).name for image_path in chunk_result.scalars().all()]
            source_paths = [Path(document.file_path) for document in deletable if document.file_path]

            await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(deletable_ids)))
            await session.execute(delete(DocumentLabel).where(DocumentLabel.document_id.in_(deletable_ids)))
            await session.execute(delete(Document).where(Document.id.in_(deletable_ids)))
            await session.commit()
            response.deleted = deletable_ids

    # 삭제된 문서를 근거로 캐시된 답이 그대로 남아있으면, 파일을 지워도 옛 답(과 그때
    # 출처로 쓰인 이미지)이 계속 재사용된다 — 라벨 수정/재추출 때와 동일하게 무효화한다.
    for document_id in response.deleted:
        invalidated = request.app.state.question_cache.invalidate_document(document_id)
        if invalidated:
            logger.info("문서 삭제로 질문 캐시 %d건 무효화: document_id=%s", invalidated, document_id)

    upload_root = _UPLOAD_DIR.resolve()
    image_root = Path(settings.image_storage_dir).resolve()
    for source_path in source_paths:
        _unlink_managed_file(source_path, upload_root, response.cleanup_warnings)
    for image_path in image_paths:
        _unlink_managed_file(image_path, image_root, response.cleanup_warnings)

    logger.info(
        "문서 삭제 완료: deleted=%d, blocked=%d, missing=%d",
        len(response.deleted),
        len(response.blocked),
        len(response.missing),
    )
    return response


@app.delete("/api/documents/{document_id}", response_model=DeleteDocumentsResponse)
async def delete_document(document_id: str, request: Request) -> DeleteDocumentsResponse:
    """문서 하나와 관련 DB·벡터·관리 파일을 삭제한다."""
    response = await _delete_documents(request, [document_id])
    if response.missing:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if response.blocked:
        raise HTTPException(status_code=409, detail=response.blocked[0].reason)
    return response


@app.post("/api/documents/delete-batch", response_model=DeleteDocumentsResponse)
async def delete_documents_batch(
    body: DeleteDocumentsRequest,
    request: Request,
) -> DeleteDocumentsResponse:
    """선택한 문서를 최대 100개까지 한 번에 정리한다. 처리 중 문서는 삭제하지 않고 이유를 반환한다."""
    return await _delete_documents(request, body.document_ids)


@app.get("/api/documents/{document_id}/chunks")
async def get_document_chunks(document_id: str) -> dict:
    """
    문서 하나의 청크를 순서대로 눈으로 훑어볼 수 있게 반환한다 (청킹/OCR 품질 확인용).
    각 청크가 텍스트/표/이미지 중 어디로 분류됐는지, 문장이 중간에 끊기지 않았는지,
    표/이미지가 제대로 마커로 감싸져서 나왔는지 등을 직접 확인하는 용도.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id).order_by(DocumentChunk.id)
        )
        chunks = result.scalars().all()

        items = []
        for c in chunks:
            if c.is_table:
                chunk_type = "table"
            elif c.image_path:
                chunk_type = "image"
            else:
                chunk_type = "text"

            items.append(
                {
                    "chunk_id": c.id,
                    "text": c.text,
                    "length": len(c.text),
                    "chunk_type": chunk_type,
                    "table_confidence": c.table_confidence,
                    "image_url": f"/images/{c.image_path}" if c.image_path else None,
                    "page_number": c.page_number,
                    "is_short": chunk_type == "text" and len(c.text) < 10,
                    "is_long": chunk_type == "text" and len(c.text) > 4000,
                }
            )

        summary = {
            "total": len(items),
            "text": sum(1 for i in items if i["chunk_type"] == "text"),
            "table": sum(1 for i in items if i["chunk_type"] == "table"),
            "image": sum(1 for i in items if i["chunk_type"] == "image"),
        }
        return {"summary": summary, "items": items}


async def _run_chat_pipeline(
    request: Request,
    body: ChatRequest,
):
    """
    질문에 대해 검색 -> 리랭킹 -> LLM 답변 생성까지 전체 파이프라인을 수행하는 제너레이터.

    각 단계마다:
      - ("progress", "단계 설명") : 단계 시작을 알림
      - ("timing", {"stage": ..., "seconds": ...}) : 그 단계가 끝나는 데 걸린 시간
    마지막에 ("result", ChatResponse)를 yield 한다.
    도중에 예외가 나면 ("error", {"stage": 실패한 단계, "message": ...})를 yield 하고 끝낸다
    (원인 단계를 몰라서 그냥 "연결이 끊겼습니다"로만 보이던 문제 방지).

    /api/chat(기존, 진행상황 없이 최종 결과만)과 /api/chat/stream(SSE, 진행상황 실시간 표시) 둘 다 이 제너레이터를 공유한다.

    추가된 것들:
      - 질문 캐싱: 완전일치는 빠르게, 의미 유사 질문은 안전조건 확인 후 재사용
      - 소프트 의도 분류: semantic cache 안전조건과 화면 진단 정보에만 사용
      - 답변 프롬프트에 근거번호+"모르면 모른다" 규칙을 넣어 환각을 억제 (재임베딩 없는 저비용 방식)
    """
    import time

    current_stage = "초기화"
    stage_timings: list[dict] = []

    # 백그라운드 워커(임베딩/청킹의 LLM 자동 라벨링)와 GPU를 동시에 잡지 않도록 직렬화한다.
    # 답변 생성이 끝날 때까지(스트리밍 도중 끊겨도 finally에서) 잠금을 들고 있는다.
    gpu_lock: asyncio.Lock = request.app.state.gpu_lock
    await gpu_lock.acquire()

    try:
        embedding_provider: BgeM3EmbeddingProvider = request.app.state.embedding_provider
        vector_store: QdrantVectorStore = request.app.state.vector_store
        reranker: BgeRerankerV2 = request.app.state.reranker
        llm_provider: QwenOllamaProvider = request.app.state.llm_provider
        intent_classifier: IntentClassifier = request.app.state.intent_classifier
        question_cache: SemanticQuestionCache = request.app.state.question_cache

        current_stage = "질문 언어 감지"
        yield ("progress", current_stage + " 중...")
        t0 = time.monotonic()
        try:
            question_language = detect_language(body.question)
        except Exception:  # noqa: BLE001
            question_language = "unknown"
        logger.info("질문 수신 (language=%s): %s", question_language, body.question)

        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        current_stage = "질문 캐시 확인"
        yield ("progress", current_stage + " 중...")
        t0 = time.monotonic()
        # 1) exact match는 의도 분류와 문서 검색을 건너뛰는 빠른 경로다.
        # 만료 항목 정리와 sliding TTL 갱신은 캐시 구성요소 내부에서 처리한다.
        exact_match = question_cache.get_exact(body.question)
        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        if exact_match is not None:
            exact_match_entry = exact_match.entry
            logger.info("질문 캐시 히트 (완전 일치): %s", body.question)
            yield (
                "result",
                ChatResponse(
                    answer=exact_match_entry.answer,
                    question_language=question_language,
                    n_context_chunks=exact_match_entry.n_context_chunks,
                    images=exact_match_entry.images,
                    sources=exact_match_entry.sources,
                    intent_scores=exact_match_entry.intent_scores,
                    cache_hit=True,
                    cache_similarity=1.0,
                    stage_timings=stage_timings,
                ),
            )
            return

        current_stage = "질문 임베딩 생성"
        yield ("progress", current_stage + " 중...")
        t0 = time.monotonic()
        search_question = expand_search_query(body.question) if settings.query_expansion_enabled else body.question
        if search_question != body.question:
            logger.info("검색어 보수적 확장: %s", search_question)
        dense_vectors, sparse_vectors = await embedding_provider.embed_hybrid([search_question])
        query_dense = dense_vectors[0]
        query_sparse = sparse_vectors[0]
        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        current_stage = "질문 의도(카테고리) 분류"
        yield ("progress", current_stage + " 중...")
        t0 = time.monotonic()
        # 2) semantic cache 안전조건과 화면 진단에 쓸 질문 의도를 계산한다.
        # 검색 순위에는 사용하지 않아 오분류가 근거를 배제하지 않는다.
        intent_scores = await intent_classifier.classify(body.question, precomputed_dense_vector=query_dense)
        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        current_stage = "의미 캐시 안전성 확인"
        yield ("progress", current_stage + " 중...")
        t0 = time.monotonic()
        query_signature = build_query_signature(
            body.question,
            available_labels=await _get_available_document_labels(),
            intent_scores=intent_scores,
        )
        semantic_match = question_cache.get_semantic(query_dense, query_signature)
        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        if semantic_match is not None:
            cached_entry = semantic_match.entry
            logger.info(
                "질문 캐시 히트 (의미 유사도=%.4f, 안전조건 일치): %s",
                semantic_match.similarity,
                body.question,
            )
            yield (
                "result",
                ChatResponse(
                    answer=cached_entry.answer,
                    question_language=question_language,
                    n_context_chunks=cached_entry.n_context_chunks,
                    images=cached_entry.images,
                    sources=cached_entry.sources,
                    intent_scores=intent_scores,
                    cache_hit=True,
                    cache_similarity=round(semantic_match.similarity, 4),
                    stage_timings=stage_timings,
                ),
            )
            return

        current_stage = "문서 검색"
        yield ("progress", f"{current_stage} 중... (풀 {settings.adaptive_retrieval_fetch_pool}개에서 상위 후보 추림)")
        t0 = time.monotonic()
        candidate_batch = await retrieve_candidates(
            body.question,
            query_dense,
            query_sparse,
            vector_store,
            reranker,
            explicit_labels=list(query_signature.labels),
        )
        candidates = candidate_batch.candidates
        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        current_stage = "리랭킹"
        t0 = time.monotonic()
        if settings.reranker_enabled and reranker.using_cuda:
            yield ("progress", f"{current_stage} 중... ({len(candidates)}개 후보 -> 상위 {settings.reranker_top_k}개)")
        elif settings.reranker_enabled:
            yield ("progress", f"{current_stage} 중... (CPU 경량 하이브리드, {len(candidates)}개 후보)")
        else:
            yield ("progress", f"{current_stage} 생략됨 (설정으로 꺼짐) — 1차 검색 상위 {settings.reranker_top_k}개 그대로 사용")
        reranked = await rerank_candidates(
            body.question,
            candidate_batch,
            reranker,
        )
        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        context_filenames: dict[str, str] = {
            str(result.metadata["document_id"]): str(result.metadata["filename"])
            for result in reranked
            if result.metadata.get("document_id") and result.metadata.get("filename")
        }

        context_blocks: list[str] = []
        for index, result in enumerate(reranked, start=1):
            document_id = result.metadata.get("document_id")
            filename = context_filenames.get(document_id, "(파일명 없음)")
            page_number = result.metadata.get("page_number")
            page_label = f" | 페이지: {page_number}" if page_number is not None else ""
            context_blocks.append(
                f"[참고 {index} | 파일: {filename}{page_label}]\n{result.text}"
            )
        context_text = "\n\n".join(context_blocks)
        language_prompt = build_cross_lingual_system_prompt(question_language=question_language, answer_language="ko")
        system_prompt = build_grounded_system_prompt(language_prompt=language_prompt)
        # 검색 순위에는 손대지 않고, 답변 단계에서 질문의 전제를 원문과 대조한다.
        # 특정 회사·제품·용어를 박지 않은 일반 규칙이므로 다른 문서에도 동일하게 적용된다.
        prompt = build_grounded_answer_prompt(question=body.question, context_text=context_text)

        current_stage = "LLM 답변 생성"
        yield ("progress", f"{current_stage} 중... (모델 크기에 따라 시간이 걸릴 수 있습니다)")
        t0 = time.monotonic()
        # 실측 결과 전체 시간의 90% 이상이 이 단계였다. 실제 계산량은 그대로지만(스트리밍이 총 시간을
        # 줄이진 않는다), 토큰이 나오는 대로 바로바로 화면에 보여주면 체감 대기시간은 크게 줄어든다.
        answer_parts: list[str] = []
        async for token in llm_provider.generate_stream(prompt=prompt, system_prompt=system_prompt):
            answer_parts.append(token)
            yield ("token", token)
        answer = "".join(answer_parts).strip()
        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        # 리랭킹 후보가 있어도(floor 안전 구조 등으로) LLM이 실제로는 답을 못 찾았다고
        # 판단하면, 그 근거 없는 후보들의 이미지/출처를 화면에 보여주면 안 된다 —
        # "확인할 수 없습니다"라고 답하면서 사진은 뜨는 모순을 막는다.
        is_grounded_answer = "확인할 수 없습니다" not in answer

        # 랭킹에 오른 후보 전부가 아니라, 답변이 실제로 "[참고 N]"으로 인용한 청크의
        # 이미지만 보여준다 — 안 그러면 리랭킹 상위 5개 중 답변에 안 쓰인 후보의 무관한
        # 이미지까지 같이 뜬다(실측으로 확인된 문제).
        cited_indices = {
            int(match) for match in _CITED_REFERENCE_PATTERN.findall(answer)
        }
        images = (
            [
                ChatImage(image_url=f"/images/{r.metadata['image_path']}", caption=r.text, chunk_id=r.chunk_id)
                for index, r in enumerate(reranked, start=1)
                if index in cited_indices and r.metadata.get("image_path")
            ]
            if is_grounded_answer
            else []
        )

        sources: list[ChatSource] = []
        if is_grounded_answer:
            # 답변에 실제로 쓰인 컨텍스트(reranked)의 출처 문서 — 문서 단위로 중복 제거하고, 그 문서에서
            # 나온 청크 중 가장 높은 유사도를 대표값으로 남긴다. 파일명은 콘솔에서 클릭해 원본을 열 때 필요하다.
            best_similarity_by_doc: dict[str, dict] = {}
            for r in reranked:
                doc_id = r.metadata.get("document_id")
                if not doc_id:
                    continue
                existing = best_similarity_by_doc.get(doc_id)
                if existing is None or r.score > existing["similarity"]:
                    best_similarity_by_doc[doc_id] = {
                        "similarity": round(r.score, 4),
                        "page_number": r.metadata.get("page_number"),
                    }

            if best_similarity_by_doc:
                sources = sorted(
                    (
                        ChatSource(
                            document_id=doc_id,
                            filename=context_filenames.get(doc_id, "(삭제된 문서)"),
                            page_number=info["page_number"],
                            similarity=info["similarity"],
                        )
                        for doc_id, info in best_similarity_by_doc.items()
                    ),
                    key=lambda s: s.similarity,
                    reverse=True,
                )

        response = ChatResponse(
            answer=answer,
            question_language=question_language,
            n_context_chunks=len(reranked),
            images=images,
            sources=sources,
            intent_scores=intent_scores,
            cache_hit=False,
            cache_similarity=None,
            stage_timings=stage_timings,
        )

        current_stage = "결과 캐시 저장"
        yield ("progress", current_stage + " 중...")
        t0 = time.monotonic()
        # 6) 답과 질문 안전 메타데이터, 실제 근거 출처를 함께 보관한다.
        # 근거 문서가 없는("모른다") 답은 캐시하지 않는다 — 이후 새 문서가 업로드돼도
        # 이 캐시를 무효화할 방법이 없어(source_document_ids가 비어 있음), 답을 찾을 수
        # 있게 된 뒤에도 의미상 비슷한 질문이 계속 "모른다"를 재사용하게 되기 때문.
        # reranked만 보면 안 된다 — 하한선 안전 구조 등으로 후보가 있어도 LLM이 실제로는
        # "확인할 수 없습니다"라고 답하는 경우가 있어(images/sources를 비우는 로직과 동일한
        # 원인), 이때도 캐시하면 새 문서를 올린 뒤에도 이 "모른다" 답이 계속 재사용된다.
        if reranked and is_grounded_answer:
            question_cache.store(
                question=body.question,
                question_vector=query_dense,
                answer=answer,
                signature=query_signature,
                source_document_ids={
                    str(result.metadata["document_id"])
                    for result in reranked
                    if result.metadata.get("document_id")
                },
                source_chunk_ids={str(result.chunk_id) for result in reranked if result.chunk_id},
                n_context_chunks=len(reranked),
                images=images,
                sources=sources,
                intent_scores=intent_scores,
            )

        async with async_session_factory() as session:
            session.add(
                ChatLog(
                    question=body.question,
                    question_language=question_language,
                    answer=answer,
                )
            )
            await session.commit()
        stage_timings.append({"stage": current_stage, "seconds": round(time.monotonic() - t0, 3)})
        yield ("timing", stage_timings[-1])

        response.stage_timings = stage_timings  # 마지막 단계(캐시 저장) 시간까지 반영해서 다시 동기화
        yield ("result", response)

    except Exception as exc:
        logger.error("답변 생성 파이프라인 실패 (단계: %s): %s", current_stage, exc, exc_info=True)
        error_payload = {"stage": current_stage, "message": str(exc), "stage_timings": stage_timings}
        yield ("error", error_payload)
    finally:
        gpu_lock.release()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """질문에 대해 검색 -> 리랭킹 -> LLM 답변 생성까지 전체 파이프라인을 수행한다 (진행상황 없이 최종 결과만)."""
    async for kind, payload in _run_chat_pipeline(request, body):
        if kind == "result":
            return payload
        if kind == "error":
            raise HTTPException(status_code=500, detail=f"[{payload['stage']}] 단계에서 실패: {payload['message']}")
    raise HTTPException(status_code=500, detail="답변 생성 파이프라인이 결과 없이 끝났습니다.")


@app.post("/api/debug/retrieve")
async def debug_retrieve(request: Request, body: ChatRequest) -> dict:
    """
    평가용: LLM 답변 생성 없이 검색+리랭킹까지만 수행하고, 실제로 반환되는 최종 청크
    목록을 문서별 중복 제거 없이 그대로 돌려준다. /api/chat의 sources는 문서당 대표
    청크 1개로 합쳐지기 때문에(응답 요약용), Recall@K/MRR@K 같은 검색 품질 평가에는
    이 엔드포인트가 필요해서 별도로 추가했다. 콘솔 UI에는 노출하지 않는다.
    """
    embedding_provider = request.app.state.embedding_provider
    vector_store = request.app.state.vector_store
    reranker = request.app.state.reranker
    intent_classifier = request.app.state.intent_classifier

    search_question = expand_search_query(body.question) if settings.query_expansion_enabled else body.question
    dense_vectors, sparse_vectors = await embedding_provider.embed_hybrid([search_question])
    query_dense = dense_vectors[0]
    query_sparse = sparse_vectors[0]
    intent_scores = await intent_classifier.classify(body.question, precomputed_dense_vector=query_dense)
    query_signature = build_query_signature(
        body.question,
        available_labels=await _get_available_document_labels(),
        intent_scores=intent_scores,
    )
    candidate_batch = await retrieve_candidates(
        body.question,
        query_dense,
        query_sparse,
        vector_store,
        reranker,
        explicit_labels=list(query_signature.labels),
    )
    reranked = await rerank_candidates(body.question, candidate_batch, reranker)

    return {
        "question": body.question,
        "results": [
            {
                "rank": index + 1,
                "chunk_id": result.chunk_id,
                "document_id": result.metadata.get("document_id"),
                "filename": result.metadata.get("filename"),
                "page": result.metadata.get("page_number"),
                "score": round(result.score, 4),
                "text": result.text,
            }
            for index, result in enumerate(reranked)
        ],
    }


@app.get("/api/chat/stream")
async def chat_stream(request: Request, question: str):
    """
    /api/chat과 동일한 파이프라인이지만, 각 단계가 끝날 때마다 SSE(Server-Sent Events)로
    진행상황·소요시간을 실시간으로 흘려보낸다. 콘솔 UI가 로딩 중 "지금 뭘 하고 있는지",
    끝난 뒤엔 "각 단계가 몇 초 걸렸는지"를 보여주는 용도. 오류가 나면 어느 단계였는지도 같이 알려준다.
    """
    from fastapi.responses import StreamingResponse

    async def event_generator():
        body = ChatRequest(question=question)
        async for kind, payload in _run_chat_pipeline(request, body):
            if kind == "progress":
                yield f"data: {json.dumps({'stage': payload})}\n\n"
            elif kind == "timing":
                yield f"data: {json.dumps({'timing': payload})}\n\n"
            elif kind == "token":
                yield f"data: {json.dumps({'token': payload})}\n\n"
            elif kind == "error":
                yield f"data: {json.dumps({'stage': 'error', 'error': payload})}\n\n"
            else:  # kind == "result"
                yield f"data: {json.dumps({'stage': 'done', 'result': payload.model_dump()})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    """DB/Qdrant/Ollama에 실제로 접속해서 상태를 확인한다. 하나라도 실패하면 503을 반환한다."""
    checks: dict[str, str] = {}

    try:
        async with async_session_factory() as session:
            await session.execute(select(1))
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = f"error: {exc}"

    try:
        await request.app.state.vector_store.ping()
        checks["qdrant"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["qdrant"] = f"error: {exc}"

    try:
        await request.app.state.llm_provider.ping()
        checks["ollama_model"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["ollama_model"] = f"error: {exc}"

    required_state = ("embedding_provider", "reranker")
    missing_state = [name for name in required_state if not hasattr(request.app.state, name)]
    checks["local_models"] = "ok" if not missing_state else f"error: not loaded: {', '.join(missing_state)}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(status_code=status_code, content={"status": "ok" if all_ok else "degraded", "checks": checks})


# Evaluation remains API-only: the browser console intentionally has no evaluation panel.
app.include_router(create_evaluation_router(_run_chat_pipeline))

app.include_router(create_chat_stream_router(_run_chat_pipeline))
app.include_router(create_documents_router(_run_workers_in_background, _UPLOAD_DIR))
app.include_router(create_work_reports_router(_UPLOAD_DIR))

# Shipment report generation is isolated from the RAG pipeline and shares only this server.
app.include_router(create_shipment_report_router())
