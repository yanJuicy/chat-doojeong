"""
추출(OCR/텍스트 파싱) 워커.

핵심: 이 워커는 DB(Document.status)만 보고 움직인다.
청킹/임베딩 워커의 존재를 전혀 모르고, 반대로도 마찬가지다.
그래서 OCR 엔진을 통째로 바꾸고 싶으면 run_once()의 extractor 생성 부분만 바꾸면 되고,
나머지 워커/서버 코드는 전혀 건드릴 필요가 없다.

구조 (찜 -> 처리 -> 저장, 3단계로 분리):
  1. 짧은 트랜잭션으로 대상 문서들을 "찜"만 한다 (status: UPLOADED -> EXTRACTING) 하고 바로 커밋한다.
     이 순간 행 잠금이 풀리지만, EXTRACTING이라는 상태 자체가 "이미 누가 집어갔다"는 표시라서
     다른 워커가 중복으로 집어가지 않는다.
  2. 잠금 없이 실제로 오래 걸리는 작업(OCR 등)을 한다. 페이지가 끝날 때마다 진행률을 즉시
     커밋해서, 다른 곳(콘솔 폴링)에서 "3/32페이지 처리 중"을 실시간으로 볼 수 있게 한다.
     여기서 잠금을 안 쥐고 있어서 이 단계가 몇 분이 걸려도 다른 작업을 안 막는다.
  3. 결과를 짧은 트랜잭션으로 저장한다 (status: EXTRACTING -> EXTRACTED 또는 FAILED/UPLOADED).

만약 2단계 도중 워커 프로세스 자체가 죽으면, 그 문서는 EXTRACTING에 멈춘 채로 남는다.
지금 규모(수동으로 워커를 트리거하는 개발/소규모 운영)에서는 이 경우가 드물고, 발견하면
`POST /api/documents/{id}/retry`로 수동 복구할 수 있어 별도의 자동 하트비트 회수 로직은
아직 안 넣었다 (나중에 여러 워커 프로세스를 상시로 돌리게 되면 그때 추가하면 된다).

독립 실행 방법 (별도 프로세스/컨테이너로도 그대로 뺄 수 있음):
    python -m app.workers.extraction_worker
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.extractor_registry import ExtractorRegistry
from ..core.extraction_quality import evaluate_extraction_quality
from ..db.models import Document, DocumentStatus

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


async def process_pending_documents(session_factory: SessionFactory, registry: ExtractorRegistry) -> int:
    """
    status=UPLOADED인 문서를 찾아 텍스트를 추출하고 상태를 갱신한다.

    Args:
        session_factory: DB 세션을 필요할 때마다 새로 만들어주는 팩토리 (예: async_session_factory).
                          문서마다 독립된 짧은 세션/트랜잭션을 쓰기 위해 단일 session 대신 이걸 받는다.
        registry: 파일 확장자에 맞는 BaseDocumentExtractor를 골라주는 레지스트리.

    Returns:
        이번 호출에서 처리한(성공+실패 포함) 문서 개수
    """
    # 1) 찜 — 짧은 트랜잭션. FOR UPDATE SKIP LOCKED로 중복 집어가기 방지, 찜하자마자 바로 커밋해서 잠금 해제.
    async with session_factory() as session:
        stale_before = datetime.now(timezone.utc) - timedelta(minutes=settings.worker_stale_after_minutes)
        stale_result = await session.execute(
            select(Document)
            .where(Document.status == DocumentStatus.EXTRACTING, Document.updated_at < stale_before)
            .limit(settings.worker_claim_batch_size)
            .with_for_update(skip_locked=True)
        )
        stale_documents = list(stale_result.scalars().all())
        for stale_doc in stale_documents:
            stale_doc.status = DocumentStatus.UPLOADED
            stale_doc.current_page = None
            stale_doc.total_pages = None
            stale_doc.warning_message = "진행률 갱신이 없어 멈춘 추출 작업을 자동 회수해 재시도합니다."
        if stale_documents:
            logger.warning("멈춘 추출 작업 %d개 자동 회수", len(stale_documents))

        result = await session.execute(
            select(Document)
            .where(Document.status == DocumentStatus.UPLOADED)
            .order_by(Document.created_at)
            .limit(settings.worker_claim_batch_size)
            .with_for_update(skip_locked=True)
        )
        documents = list(result.scalars().all())
        document_ids = [doc.id for doc in documents]
        for doc in documents:
            doc.status = DocumentStatus.EXTRACTING
        await session.commit()

    if document_ids:
        logger.info("추출 대상 %d개 문서 찜 완료, 처리 시작", len(document_ids))

    # 2)+3) 각 문서를 독립적으로 처리 (잠금 없이 오래 걸리는 작업 + 결과 저장)
    for document_id in document_ids:
        await _process_one_document(session_factory, document_id, registry)

    return len(document_ids)


async def _process_one_document(session_factory: SessionFactory, document_id: str, registry: ExtractorRegistry) -> None:
    async with session_factory() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return

        async def on_progress(current_page: int, total_pages: int) -> None:
            # 진행률은 즉시 커밋해서 폴링하는 쪽에서 바로 보이게 한다 (본 결과 저장 트랜잭션과는 별개).
            doc.current_page = current_page
            doc.total_pages = total_pages
            doc.updated_at = datetime.now(timezone.utc)
            await session.commit()

        try:
            if not doc.file_path:
                raise ValueError("file_path가 없는 문서는 추출할 수 없습니다.")
            extractor = await registry.get_for_file(doc.file_path)
            text = await extractor.extract(doc.file_path, on_progress=on_progress)
            quality = evaluate_extraction_quality(text)
            doc.raw_text = text
            doc.extraction_quality_score = quality.score
            quality_details = quality.to_dict()
            page_diagnostics = getattr(extractor, "last_page_diagnostics", None)
            if page_diagnostics:
                quality_details["pages"] = page_diagnostics
            doc.extraction_quality_details = json.dumps(quality_details, ensure_ascii=False)
            suffix = Path(doc.file_path).suffix.lower()
            doc.extraction_method = getattr(
                extractor,
                "last_extraction_method",
                "ocr_or_mixed" if suffix in {".pdf", ".jpg", ".jpeg", ".png"} else "native_text",
            )
            doc.pipeline_version = "2026.08-quality-v5-pdf-fast"
            is_ocr_document = suffix in {".pdf", ".jpg", ".jpeg", ".png"}
            if (
                settings.ocr_quality_gate_enabled
                and is_ocr_document
                and quality.score < settings.ocr_quality_min_score
            ):
                doc.status = DocumentStatus.NEEDS_REVIEW
                reason_text = ", ".join(quality.reasons) or "OCR 품질 점수가 기준 미달"
                doc.warning_message = (
                    f"추출 품질 검토 필요(score={quality.score:.3f} < "
                    f"{settings.ocr_quality_min_score:.3f}): {reason_text}"
                )
                logger.warning("추출 품질 게이트 차단: document_id=%s -> %s", doc.id, doc.warning_message)
            else:
                doc.status = DocumentStatus.EXTRACTED
                doc.warning_message = None
            doc.retry_count = 0  # 성공했으니 재시도 카운트 리셋
            doc.current_page = None
            doc.total_pages = None
            doc.error_message = None
            logger.info("추출 완료: document_id=%s (%d자, 품질 %.3f, status=%s)", doc.id, len(text), quality.score, doc.status.value)
        except Exception as exc:  # noqa: BLE001
            doc.retry_count += 1
            doc.current_page = None
            doc.total_pages = None
            if doc.retry_count < settings.worker_max_retries:
                # UPLOADED로 되돌려서 다음 워커 실행 때 자동으로 다시 찜해서 재시도되게 한다.
                doc.status = DocumentStatus.UPLOADED
                doc.error_message = f"[{doc.retry_count}/{settings.worker_max_retries}회 시도 실패, 자동 재시도 예정] {exc}"
                logger.warning(
                    "추출 실패 (재시도 %d/%d): document_id=%s (%s)",
                    doc.retry_count,
                    settings.worker_max_retries,
                    doc.id,
                    exc,
                )
            else:
                doc.status = DocumentStatus.FAILED
                doc.error_message = f"[{doc.retry_count}회 재시도 모두 실패] {exc}"
                logger.error("추출 최종 실패 (재시도 %d회 소진): document_id=%s (%s)", doc.retry_count, doc.id, exc)

        await session.commit()


async def run_once() -> None:
    """standalone 실행 진입점."""
    from ..core.extractor_registry import extractor_registry
    from ..db.session import async_session_factory

    n = await process_pending_documents(async_session_factory, extractor_registry)
    logger.info("이번 실행에서 %d개 문서 처리", n)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(run_once())
