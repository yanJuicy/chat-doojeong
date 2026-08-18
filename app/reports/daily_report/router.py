"""일일 업무 보고서 API.

엔드포인트 2개:
  POST /api/reports/daily/generate   -> 입력 폼을 받아 보고서(마크다운)로 조립
  GET  /api/reports/daily/reference  -> 참고자료 검색(문서+채팅기록), 화면에서 복사/붙여넣기용

main.py엔 아래 한 줄만 추가하면 된다 (이유빈 님의 shipment 라우터와 동일한 방식):
  app.include_router(create_daily_report_router())
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import or_, select

from ...core.retrieval_pipeline import retrieve_candidates
from ...db.models import ChatLog
from ...db.session import async_session_factory
from .models import (
    DailyReportRequest,
    DailyReportResult,
    ReferenceItem,
    ReferenceSearchResult,
    ReferenceSource,
)
from .service import DailyReportService

_REFERENCE_LIMIT = 5  # 문서/채팅기록 각각 몇 개까지 참고자료로 보여줄지


def create_daily_report_router() -> APIRouter:
    router = APIRouter(prefix="/api/reports/daily", tags=["daily-report"])
    service = DailyReportService()

    @router.post("/generate", response_model=DailyReportResult)
    async def generate_daily_report(body: DailyReportRequest) -> DailyReportResult:
        """입력 폼을 검증하고 마크다운 보고서로 조립한다. 실패하면 status=failed + issues로 이유를 알려준다."""
        return service.generate(body)

    @router.get("/reference", response_model=ReferenceSearchResult)
    async def search_reference_material(q: str, request: Request) -> ReferenceSearchResult:
        """
        참고자료를 문서(RAG 검색)와 최근 채팅 기록 양쪽에서 찾아 반환한다.
        화면은 이 결과를 패널에 그대로 텍스트로 뿌려주기만 하면 되고,
        복사/붙여넣기는 브라우저 기본 기능이라 별도 구현이 필요 없다.
        """
        items: list[ReferenceItem] = []

        # 1) 기존 문서에서 검색 (이미 만들어진 RAG 파이프라인 재사용)
        embedding_provider = request.app.state.embedding_provider
        vector_store = request.app.state.vector_store
        reranker = request.app.state.reranker
        dense_vectors, sparse_vectors = await embedding_provider.embed_hybrid([q])
        candidate_batch = await retrieve_candidates(
            q, dense_vectors[0], sparse_vectors[0], vector_store, reranker, explicit_labels=[],
        )
        # 같은 문서에서 청크 여러 개가 상위권을 도배하지 않도록, 문서당 가장 점수 높은
        # 청크 하나만 참고자료로 보여준다 (참고자료 패널은 "다양한 자료를 훑어보는" 용도).
        # document_id가 아니라 제목(filename) 기준으로 중복 제거한다 — 재크롤링 등으로
        # 내용은 거의 같은데 별개 문서로 등록된 경우까지 참고자료 화면에서는 하나로 취급한다.
        seen_titles: set[str] = set()
        for candidate in candidate_batch.candidates:
            doc_id = str(candidate.metadata.get("document_id") or candidate.chunk_id)
            title = str(candidate.metadata.get("filename") or "(파일명 없음)")
            if title in seen_titles:
                continue
            seen_titles.add(title)
            items.append(
                ReferenceItem(
                    source=ReferenceSource.DOCUMENT,
                    title=str(candidate.metadata.get("filename") or "(파일명 없음)"),
                    snippet=candidate.text,
                    reference_id=doc_id,
                )
            )
            if len(seen_titles) >= _REFERENCE_LIMIT:
                break

        # 2) 최근 채팅 기록에서 검색 (질문/답변 텍스트 단순 포함 검색 — 임베딩 저장은 안 함)
        async with async_session_factory() as session:
            result = await session.execute(
                select(ChatLog)
                .where(or_(ChatLog.question.ilike(f"%{q}%"), ChatLog.answer.ilike(f"%{q}%")))
                .order_by(ChatLog.created_at.desc())
                .limit(_REFERENCE_LIMIT)
            )
            for log in result.scalars().all():
                items.append(
                    ReferenceItem(
                        source=ReferenceSource.CHAT_LOG,
                        title=log.question,
                        snippet=log.answer,
                        reference_id=log.id,
                        created_at=log.created_at.isoformat() if log.created_at else None,
                    )
                )

        return ReferenceSearchResult(query=q, items=items)

    return router
