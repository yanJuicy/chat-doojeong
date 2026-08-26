"""
일회성 백필: work_report_entries/work_report_documents(옛 테이블)의 데이터를 통합된
documents 테이블(WeeklyReportEntry/WeeklyReportSource, document_type_id=2/3)로 옮기고,
항목들의 검색용 raw_text/청크/임베딩을 다시 만든다.

id를 그대로 재사용하는 행(work_report_indexing.py가 예전에 만들어둔 "그림자 문서")이
이미 documents 테이블에 document_type_id=1(rag_upload)로 들어있을 수 있어서, 데이터 이관은
ORM이 아니라 `INSERT ... ON CONFLICT (id) DO UPDATE`로 한다 — SQLAlchemy 단일 테이블 상속은
`session.get(WeeklyReportEntry, id)`가 document_type_id까지 같이 걸어서 조회하기 때문에,
아직 document_type_id가 안 바뀐 행은 "없음"으로 오판해서 같은 id로 다시 INSERT하려다
PK 충돌을 낸다 — 그래서 이 단계만 raw SQL로 한다.

실행 후 결과를 확인하고, 문제 없으면 0013 마이그레이션으로 구 테이블을 지운다.

실행: "C:\\v\\rag_latest\\Scripts\\python.exe" -m scripts.backfill_weekly_reports
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.core.bge_m3_provider import BgeM3EmbeddingProvider
from app.core.qdrant_store import QdrantVectorStore
from app.db.models import DocumentChunk, DocumentLabel, DocumentStatus, WeeklyReportEntry
from app.db.session import async_session_factory
from app.workers.embedding_worker import process_pending_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_MARKER_LABEL = "주간보고서"

_UPSERT_SOURCES_SQL = text(
    """
    INSERT INTO documents (
        id, document_type_id, filename, file_path, subject, status, type_specific_data,
        created_at, updated_at
    )
    SELECT
        id, 3, filename, file_path, department, 'ready',
        jsonb_build_object(
            'pages_with_table', pages_with_table,
            'pages_without_table', pages_without_table,
            'entries_created', entries_created
        ),
        uploaded_at, uploaded_at
    FROM work_report_documents
    ON CONFLICT (id) DO UPDATE SET
        document_type_id = 3,
        filename = EXCLUDED.filename,
        file_path = EXCLUDED.file_path,
        subject = EXCLUDED.subject,
        status = 'ready',
        type_specific_data = EXCLUDED.type_specific_data
    """
)

_UPSERT_ENTRIES_SQL = text(
    """
    INSERT INTO documents (
        id, document_type_id, filename, subject, period_start, period_end, content,
        source, source_document_id, raw_input, type_specific_data, status, created_at, updated_at
    )
    SELECT
        id, 2, '주간보고_' || department || '_' || period_start::text, department,
        period_start, period_end, content, source, source_document_id, raw_input,
        jsonb_build_object(
            'entry_type', entry_type,
            'source_category', source_category,
            'source_format', source_format
        ),
        'uploaded', created_at, created_at
    FROM work_report_entries
    ON CONFLICT (id) DO UPDATE SET
        document_type_id = 2,
        filename = EXCLUDED.filename,
        subject = EXCLUDED.subject,
        period_start = EXCLUDED.period_start,
        period_end = EXCLUDED.period_end,
        content = EXCLUDED.content,
        source = EXCLUDED.source,
        source_document_id = EXCLUDED.source_document_id,
        raw_input = EXCLUDED.raw_input,
        type_specific_data = EXCLUDED.type_specific_data
    RETURNING id
    """
)


def _summary_text(entry: WeeklyReportEntry) -> str:
    entry_type_label = "실적" if entry.entry_type == "실적" else "계획"
    category = f" ({entry.source_category})" if entry.source_category else ""
    period = f"{entry.period_start.isoformat()}~{entry.period_end.isoformat()}"
    return (
        f"[문서: 주간보고서, {entry.department}]\n"
        f"{entry.department} {period} 주간업무 {entry_type_label}{category}: {entry.content}"
    )


async def rebuild_search_index(entry_ids: list[str], embedding_provider, vector_store) -> None:
    """entry들의 raw_text/DocumentChunk/라벨을 다시 만들고 일괄 임베딩한다."""
    async with async_session_factory() as session:
        for entry_id in entry_ids:
            entry = await session.get(WeeklyReportEntry, entry_id)
            if entry is None:
                logger.warning("백필된 entry를 WeeklyReportEntry로 다시 못 찾음: id=%s", entry_id)
                continue
            entry.raw_text = _summary_text(entry)
            entry.status = DocumentStatus.CHUNKED

            for label in (_MARKER_LABEL, entry.department):
                existing = await session.execute(
                    text("SELECT id FROM document_labels WHERE document_id=:did AND label=:label"),
                    {"did": entry_id, "label": label},
                )
                if existing.first() is None:
                    session.add(DocumentLabel(document_id=entry_id, label=label))

            await session.execute(text("DELETE FROM document_chunks WHERE document_id=:did"), {"did": entry_id})
            session.add(DocumentChunk(id=entry_id, document_id=entry_id, text=entry.raw_text, embedded=False))
        await session.commit()

        total = 0
        while True:
            processed = await process_pending_chunks(session, embedding_provider, vector_store)
            total += processed
            if processed == 0:
                break
        logger.info("임베딩 완료: %d개 청크", total)


async def main() -> None:
    async with async_session_factory() as session:
        source_result = await session.execute(_UPSERT_SOURCES_SQL)
        await session.commit()
        entry_result = await session.execute(_UPSERT_ENTRIES_SQL)
        entry_ids = [row[0] for row in entry_result.all()]
        await session.commit()
    logger.info("주간보고서 원본 문서 이관 완료, 항목 이관: %d건", len(entry_ids))

    embedding_provider = BgeM3EmbeddingProvider()
    vector_store = QdrantVectorStore()
    await vector_store.ensure_collection()
    await rebuild_search_index(entry_ids, embedding_provider, vector_store)


if __name__ == "__main__":
    asyncio.run(main())
