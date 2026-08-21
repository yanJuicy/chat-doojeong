"""
주간보고서 항목(WorkReportEntry)을 일반 RAG 검색에서도 찾을 수 있게 잇는 얇은 다리.

설계: 새 검색 경로를 만들지 않는다. 항목이 저장/수정/삭제될 때마다 그 항목 하나를
대표하는 Document 1개 + DocumentChunk 1개를 만들어(또는 지워서) 기존 documents/
document_chunks 테이블에 끼워 넣기만 한다. 그러면 이미 있는 embedding_worker가
평소처럼 이 청크를 주워서 Qdrant에 넣고, 이미 있는 retrieval_pipeline이 평소처럼
검색해준다 — 워커/검색 코드는 한 줄도 안 바꾼다.

Document.id는 WorkReportEntry.id와 항상 같은 값을 쓴다(1:1). 그래서 별도 매핑
테이블 없이 entry_id로 바로 대응하는 Document/DocumentChunk를 찾아 지울 수 있다.

원본 상세 데이터(entry.content 등)는 여전히 work_report_entries에만 있고, Qdrant에는
검색용 요약 텍스트만 들어간다 — 문서 전체를 통째로 저장하지 않는다는 원칙과 동일하게,
여기서도 원본은 SQL 테이블에만 두고 검색 인덱스에는 요약만 둔다.

LLM을 쓰지 않는다 — 템플릿 문자열 조합만 사용한다(정규식/예측 가능한 방식 선호 원칙과 동일).
"""
from __future__ import annotations

import logging

from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from .embeddings import BaseEmbeddingProvider
from .vector_store import BaseVectorStore
from ..db.models import Document, DocumentChunk, DocumentLabel, DocumentStatus, WorkReportEntry
from ..workers.embedding_worker import process_pending_chunks

logger = logging.getLogger(__name__)

_MARKER_LABEL = "주간보고서"


def _build_summary_text(entry: WorkReportEntry) -> str:
    """LLM 없이 조립하는 검색용 요약 문장."""
    entry_type_label = "실적" if entry.entry_type == "실적" else "계획"
    category = f" ({entry.source_category})" if entry.source_category else ""
    period = f"{entry.period_start.isoformat()}~{entry.period_end.isoformat()}"
    return (
        f"[문서: 주간보고서, {entry.department}]\n"
        f"{entry.department} {period} 주간업무 {entry_type_label}{category}: {entry.content}"
    )


async def index_entry(
    session: AsyncSession,
    embedding_provider: BaseEmbeddingProvider,
    vector_store: BaseVectorStore,
    entry: WorkReportEntry,
) -> None:
    """entry 하나를 대표하는 Document+DocumentChunk를 만들고 즉시 임베딩까지 마친다."""
    document = await session.get(Document, entry.id)
    if document is None:
        document = Document(
            id=entry.id,
            filename=f"주간보고_{entry.department}_{entry.period_start.isoformat()}",
            status=DocumentStatus.CHUNKED,
        )
        session.add(document)
        session.add(DocumentLabel(document_id=entry.id, label=_MARKER_LABEL))
        session.add(DocumentLabel(document_id=entry.id, label=entry.department))
    else:
        document.status = DocumentStatus.CHUNKED

    await session.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == entry.id))
    session.add(
        DocumentChunk(
            id=entry.id,
            document_id=entry.id,
            text=_build_summary_text(entry),
            embedded=False,
        )
    )
    await session.commit()

    # 방금 넣은 청크(그리고 우연히 같이 대기 중이던 다른 청크가 있다면 그것까지)를 바로 임베딩한다 —
    # 요약 텍스트 하나뿐이라 워커를 기다리지 않고 요청 안에서 처리해도 지연이 미미하다.
    await process_pending_chunks(session, embedding_provider, vector_store)


async def deindex_entry(session: AsyncSession, vector_store: BaseVectorStore, entry_id: str) -> None:
    """entry_id에 대응하는 Document/DocumentChunk와 Qdrant 벡터를 지운다."""
    await session.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == entry_id))
    await session.execute(sa_delete(DocumentLabel).where(DocumentLabel.document_id == entry_id))
    document = await session.get(Document, entry_id)
    if document is not None:
        await session.delete(document)
    await session.commit()
    await vector_store.delete_by_document_id(entry_id)
