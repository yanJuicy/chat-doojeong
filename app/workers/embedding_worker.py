"""
임베딩 워커.

청킹 워커가 어떤 청킹 전략을 썼는지 모르고, DocumentChunk 테이블의 텍스트만 본다.
임베딩 모델/벡터DB를 Qdrant에서 FAISS 등으로 바꿔도 이 워커의 로직(쿼리-임베딩-upsert-상태갱신)은
그대로이고, 주입되는 embedding_provider/vector_store 구현체만 바뀐다.

속도 최적화:
  - 청크마다 개별 호출하지 않고, embed_hybrid()에 텍스트를 batch로 묶어서 전달한다
    (bge-m3는 배치 인코딩이 훨씬 빠르다 — 청크 하나씩 왕복하는 것보다 몇 배 이득).
  - 벡터DB 저장(upsert)은 청크마다 독립적인 작업이라 asyncio.gather로 동시에 실행한다.

독립 실행:
    python -m app.workers.embedding_worker
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.embeddings import BaseEmbeddingProvider
from ..core.vector_store import BaseVectorStore
from ..db.models import Document, DocumentChunk, DocumentLabel, DocumentStatus

logger = logging.getLogger(__name__)

# 한 번에 인코딩할 청크 개수. 너무 크면 모델 서버(GPU) 메모리 부담이 커지므로 적당히 나눈다.
_ENCODE_BATCH_SIZE = 32
# 벡터DB upsert 동시 실행 개수 제한 (무제한 동시 요청으로 벡터DB에 부하를 주지 않도록)
_UPSERT_CONCURRENCY = 16


async def process_pending_chunks(
    session: AsyncSession,
    embedding_provider: BaseEmbeddingProvider,
    vector_store: BaseVectorStore,
) -> int:
    """
    embedded=False인 청크를 배치로 임베딩해서 벡터DB에 동시 저장하고, 문서 단위로 완료 여부를 갱신한다.

    안정성 개선:
      - 행 잠금(FOR UPDATE SKIP LOCKED)으로 이 워커가 동시에 여러 번 실행돼도 같은 청크를 중복 임베딩하지 않는다.
      - 예전엔 커밋을 맨 마지막에 딱 한 번만 해서, 배치 하나가 실패하면 그 전에 이미 성공한 배치까지
        전부 롤백되어 날아갔다. 지금은 배치마다 커밋해서, 중간에 실패해도 그 전까지의 진행상황은 지켜진다.
      - 배치 하나가 계속 실패하면(예: 그 배치 안의 특정 텍스트가 계속 문제를 일으킴) 그 청크들의
        embed_retry_count를 올리고, 상한을 넘으면 다음 실행부터는 아예 조회 대상에서 제외해서
        무한 재시도로 매번 시간을 낭비하지 않게 한다.
    """
    result = await session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.embedded == False, DocumentChunk.embed_retry_count < settings.worker_max_retries)  # noqa: E712
        .limit(min(settings.embedding_claim_batch_size, _ENCODE_BATCH_SIZE))
        .with_for_update(skip_locked=True)
    )
    chunks = list(result.scalars().all())

    document_ids = {chunk.document_id for chunk in chunks}
    documents_by_id: dict[str, Document] = {}
    labels_by_document: dict[str, list[str]] = {}
    if document_ids:
        document_result = await session.execute(select(Document).where(Document.id.in_(document_ids)))
        documents_by_id = {document.id: document for document in document_result.scalars().all()}
        label_result = await session.execute(
            select(DocumentLabel.document_id, DocumentLabel.label).where(DocumentLabel.document_id.in_(document_ids))
        )
        for document_id, label in label_result.all():
            labels_by_document.setdefault(document_id, []).append(label)

    touched_document_ids: set[str] = set()
    processed_count = 0
    upsert_semaphore = asyncio.Semaphore(_UPSERT_CONCURRENCY)

    async def upsert_one(chunk: DocumentChunk, dense_vector: list[float], sparse_vector: dict[int, float]) -> None:
        async with upsert_semaphore:
            document = documents_by_id.get(chunk.document_id)
            await vector_store.upsert(
                chunk_id=chunk.id,
                text=chunk.text,
                dense_vector=dense_vector,
                sparse_vector=sparse_vector,
                metadata={
                    "document_id": chunk.document_id,
                    "is_table": chunk.is_table,
                    "image_path": chunk.image_path,
                    "page_number": chunk.page_number,
                    "filename": document.filename if document else None,
                    "category": document.category if document else None,
                    "labels": labels_by_document.get(chunk.document_id, []),
                    "pipeline_version": document.pipeline_version if document else None,
                },
            )

    for batch_start in range(0, len(chunks), _ENCODE_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + _ENCODE_BATCH_SIZE]
        texts = [c.text for c in batch]
        batch_ids = [c.id for c in batch]

        try:
            # BGE-M3 한 번의 추론으로 dense+sparse를 같이 만든다. 과거 사전계산 dense 최적화보다
            # 질문/문서 모두 이중 모델 통과를 없애는 편이 일관되고 실제 배치 처리에도 유리하다.
            dense_vectors, sparse_vectors = await embedding_provider.embed_hybrid(texts)

            await asyncio.gather(
                *(
                    upsert_one(chunk, dense_vec, sparse_vec)
                    for chunk, dense_vec, sparse_vec in zip(batch, dense_vectors, sparse_vectors)
                )
            )

            for chunk in batch:
                chunk.embedded = True
                chunk.embed_retry_count = 0
                touched_document_ids.add(chunk.document_id)
            processed_count += len(batch)

            # 배치마다 커밋 — 이후 배치가 실패해도 여기까지는 이미 지켜진다.
            await session.commit()
            logger.info(
                "배치 임베딩 완료: %d/%d (재사용 %d개, 신규계산 %d개)",
                min(batch_start + _ENCODE_BATCH_SIZE, len(chunks)),
                len(chunks),
                0,
                len(batch),
            )
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            # rollback 뒤 기존 ORM 객체는 만료될 수 있으므로 ID로 다시 읽어서 재시도 횟수를 갱신한다.
            failed_result = await session.execute(
                select(DocumentChunk).where(DocumentChunk.id.in_(batch_ids)).with_for_update()
            )
            failed_chunks = list(failed_result.scalars().all())
            for chunk in failed_chunks:
                chunk.embed_retry_count += 1
                if chunk.embed_retry_count >= settings.worker_max_retries:
                    logger.error(
                        "청크 임베딩 최종 실패(재시도 %d회 소진), 다음 실행부터 제외됨: chunk_id=%s (%s)",
                        chunk.embed_retry_count,
                        chunk.id,
                        exc,
                    )
                else:
                    logger.warning(
                        "배치 임베딩 실패 (재시도 %d/%d), 이 배치만 건너뛰고 계속 진행: chunk_id=%s (%s)",
                        chunk.embed_retry_count,
                        settings.worker_max_retries,
                        chunk.id,
                        exc,
                    )
            await session.commit()  # retry_count 갱신만 반영 (embedded는 그대로 False)

    # 이번에 처리된 문서 중, 모든 청크가 embedded=True가 된 문서는 READY로 승격한다.
    for document_id in touched_document_ids:
        remaining = await session.execute(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.embedded == False,  # noqa: E712
            )
        )
        if remaining.scalars().first() is None:
            doc = await session.get(Document, document_id)
            if doc is not None:
                doc.status = DocumentStatus.READY
                doc.indexed_at = func.now()
                logger.info("문서 준비 완료(검색 가능): document_id=%s", document_id)

    await session.commit()
    logger.info("이번 실행에서 %d개 청크 임베딩", processed_count)
    return processed_count


async def run_once() -> None:
    """standalone 실행 진입점. 임베딩/벡터DB 구현체를 구체적으로 아는 곳은 여기뿐이다."""
    from ..core.bge_m3_provider import BgeM3EmbeddingProvider
    from ..core.qdrant_store import QdrantVectorStore
    from ..db.session import async_session_factory

    embedding_provider: BaseEmbeddingProvider = BgeM3EmbeddingProvider()
    vector_store: BaseVectorStore = QdrantVectorStore()
    await vector_store.ensure_collection()

    async with async_session_factory() as session:
        n = await process_pending_chunks(session, embedding_provider, vector_store)
        logger.info("이번 실행에서 %d개 청크 처리", n)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(run_once())
