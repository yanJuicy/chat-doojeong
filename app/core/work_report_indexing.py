"""
WeeklyReportEntry(=documents 테이블의 행) 검색 인덱싱.

통합 전에는 work_report_entries가 별도 테이블이라, 검색에 잡히게 하려고 매번
그림자 Document+DocumentChunk를 복제해서 만들었다. 지금은 WeeklyReportEntry 자체가
documents 테이블의 행이라 복제가 필요 없다 — 이 행의 raw_text를 템플릿 요약으로
채우고 DocumentChunk 하나를 만들어(갱신해서) 기존 embedding_worker에 태우기만 하면 된다.

인덱싱 타이밍은 저장과 같은 요청 안에서 즉시 처리한다(워커 폴링 주기까지 기다리지 않음) —
docs/DB_확장_구조_설계초안.md 4번 항목 참고. 그래야 채팅으로 항목을 추가하자마자
챗봇 질문에서 바로 찾아지는 지금 동작이 유지된다.

LLM을 쓰지 않는다 — 템플릿 문자열 조합만 사용한다(정규식/예측 가능한 방식 선호 원칙과 동일).
"""
from __future__ import annotations

import logging

from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings import BaseEmbeddingProvider
from .vector_store import BaseVectorStore
from ..db.models import DocumentChunk, DocumentLabel, DocumentStatus, WeeklyReportEntry
from ..workers.embedding_worker import process_pending_chunks

logger = logging.getLogger(__name__)

_MARKER_LABEL = "주간보고서"


def _build_summary_text(entry: WeeklyReportEntry) -> str:
    """LLM 없이 조립하는 검색용 요약 문장."""
    entry_type_label = "실적" if entry.entry_type == "실적" else "계획"
    category = f" ({entry.source_category})" if entry.source_category else ""
    period = f"{entry.period_start.isoformat()}~{entry.period_end.isoformat()}"
    return (
        f"[문서: 주간보고서, {entry.department}]\n"
        f"{entry.department} {period} 주간업무 {entry_type_label}{category}: {entry.content}"
    )


async def _ensure_label(session: AsyncSession, document_id: str, label: str) -> None:
    existing = await session.execute(
        select(DocumentLabel.id).where(DocumentLabel.document_id == document_id, DocumentLabel.label == label)
    )
    if existing.scalar_one_or_none() is None:
        session.add(DocumentLabel(document_id=document_id, label=label))


async def index_entry(
    session: AsyncSession,
    embedding_provider: BaseEmbeddingProvider,
    vector_store: BaseVectorStore,
    entry: WeeklyReportEntry,
) -> None:
    """entry(=documents 행 자신)의 raw_text/청크를 최신 상태로 맞추고 즉시 임베딩까지 마친다."""
    entry.raw_text = _build_summary_text(entry)
    entry.status = DocumentStatus.CHUNKED
    entry.filename = f"주간보고_{entry.department}_{entry.period_start.isoformat()}"

    await _ensure_label(session, entry.id, _MARKER_LABEL)
    await _ensure_label(session, entry.id, entry.department)

    await session.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == entry.id))
    session.add(
        DocumentChunk(
            id=entry.id,
            document_id=entry.id,
            text=entry.raw_text,
            embedded=False,
        )
    )
    await session.commit()

    # 방금 넣은 청크(그리고 우연히 같이 대기 중이던 다른 청크가 있다면 그것까지)를 바로 임베딩한다 —
    # 요약 텍스트 하나뿐이라 워커를 기다리지 않고 요청 안에서 처리해도 지연이 미미하다.
    await process_pending_chunks(session, embedding_provider, vector_store)


async def deindex_entry(session: AsyncSession, vector_store: BaseVectorStore, entry_id: str) -> None:
    """entry_id에 대응하는 청크/라벨/Document 행과 Qdrant 벡터를 지운다."""
    await session.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == entry_id))
    await session.execute(sa_delete(DocumentLabel).where(DocumentLabel.document_id == entry_id))
    entry = await session.get(WeeklyReportEntry, entry_id)
    if entry is not None:
        await session.delete(entry)
    await session.commit()
    await vector_store.delete_by_document_id(entry_id)
