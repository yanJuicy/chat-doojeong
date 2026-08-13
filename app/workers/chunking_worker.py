"""
청킹 워커.

extraction_worker가 뭘로(PyMuPDF든 PaddleOCR든 다른 OCR API든) 텍스트를 뽑았는지 전혀 모른다.
그저 Document.raw_text(문자열)만 보고 청킹해서 DocumentChunk 행으로 저장한다.

독립 실행:
    python -m app.workers.chunking_worker
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..core.chunking import BaseChunker
from ..core.chunk_validator import validate_chunks
from ..core.intent_classifier import IntentClassifier
from ..core.label_generation import parse_generated_labels
from ..core.similarity_utils import cosine_similarity
from ..core.table_confidence import compute_table_confidence
from ..db.models import Document, DocumentChunk, DocumentLabel, DocumentStatus

logger = logging.getLogger(__name__)

# 라벨 재분류 임계값 (사용자와 논의해서 확정한 두 가지 규칙)
# - LABEL_SWAP_MARGIN: 지금 라벨보다 이만큼 더 잘 맞는 "기존" 라벨이 있으면 그걸로 교체한다.
# - LABEL_ABSOLUTE_FLOOR: 대안이 있든 없든, 지금 라벨의 유사도 자체가 이 밑이면 그냥 라벨을 버린다
#   (= 내용을 안 보고 아무렇게나 붙인 라벨을 걸러내는 안전장치. 실제 임베딩 모델 기준으로
#   운영해보면서 값을 조정할 여지가 있다 -- 너무 낮으면 안 걸러지고, 너무 높으면 멀쩡한 라벨도 날아간다).
LABEL_SWAP_MARGIN = 0.2
LABEL_ABSOLUTE_FLOOR = 0.15


async def process_pending_documents(
    session: AsyncSession,
    chunker: BaseChunker,
    intent_classifier: IntentClassifier | None = None,
    embedding_provider=None,
    llm_provider=None,
) -> int:
    """
    status=EXTRACTED인 문서를 청킹해서 DocumentChunk로 저장하고 상태를 CHUNKED로 올린다.
    intent_classifier가 주어지면, 문서 전체 텍스트로 소프트 카테고리 분류도 같이 수행해서
    Document.category / category_similarity에 기록한다 (검색 시 가산점으로만 쓰이고 배제엔 안 씀).
    embedding_provider가 주어지면, 문서에 붙은 라벨(들)이 실제 내용과 잘 맞는지도 확인해서
    조용히 교정/제거한다 (아래 _reclassify_document_labels 참고).
    llm_provider가 주어지면, 라벨이 하나도 없는 문서에 한해 LLM이 대신 라벨을 지어준다
    (아래 _generate_label_via_llm 참고) — 사람이 라벨을 안 붙여도 되게 하려는 목적.

    중복 처리 방지와 실패 복구는 extraction_worker와 동일한 방식(FOR UPDATE SKIP LOCKED + retry_count)을 쓴다.
    """
    result = await session.execute(
        select(Document)
        .where(Document.status == DocumentStatus.EXTRACTED)
        .order_by(Document.created_at)
        .limit(settings.worker_claim_batch_size)
        .with_for_update(skip_locked=True)
    )
    documents = list(result.scalars().all())

    for doc in documents:
        try:
            if not doc.raw_text:
                raise ValueError("raw_text가 비어있는 문서는 청킹할 수 없습니다.")
            chunks = await chunker.split(document_id=doc.id, text=doc.raw_text)

            # 청크 접두어를 만들기 전에, 라벨들이 내용이랑 완전히 동떨어져 보이면 먼저 조용히
            # 바로잡는다 — 그래야 접두어에 "교정 전" 라벨이 박히는 걸 막을 수 있다.
            if embedding_provider is not None:
                try:
                    # 라벨이 없으면 회사/모델/주제/문서종류를 여러 축으로 생성한다. 하나의 모호한
                    # 라벨만 만들면 질문 표현이 조금 달라졌을 때 연결고리가 사라지기 쉽다.
                    existing_count_result = await session.execute(
                        select(func.count(DocumentLabel.id)).where(DocumentLabel.document_id == doc.id)
                    )
                    existing_count = int(existing_count_result.scalar() or 0)
                    should_generate = settings.auto_generate_labels_enabled and existing_count == 0
                    should_enrich = settings.auto_enrich_labels_enabled and existing_count < settings.auto_label_min_count
                    if (should_generate or should_enrich) and llm_provider is not None:
                        generated_labels = await _generate_labels_via_llm(doc, llm_provider)
                        existing_labels_result = await session.execute(
                            select(DocumentLabel.label).where(DocumentLabel.document_id == doc.id)
                        )
                        existing_labels = {row[0].casefold() for row in existing_labels_result.all()}
                        remaining_slots = max(0, settings.auto_label_max_count - existing_count)
                        new_labels = [
                            label for label in generated_labels
                            if label.casefold() not in existing_labels
                        ][:remaining_slots]
                        for generated_label in new_labels:
                            session.add(DocumentLabel(id=str(uuid.uuid4()), document_id=doc.id, label=generated_label))
                        if new_labels:
                            logger.info("LLM이 검색 라벨 보강: document_id=%s -> %s", doc.id, new_labels)

                    # 방금 LLM이 지어낸 라벨이든, 사람이 붙인 라벨이든 — 여기서 기존 라벨 풀과 비교해서
                    # 표기만 다르고 사실상 같은 대상이면 자동으로 합쳐진다 (병합 로직 재사용).
                    if settings.auto_reclassify_labels_enabled:
                        await _reclassify_document_labels(doc, embedding_provider, session)
                except Exception as label_exc:  # noqa: BLE001
                    # 부가 기능이라 실패해도 청킹 자체는 계속 진행시킨다.
                    logger.warning("라벨 자동교정 실패(청킹은 정상 진행): document_id=%s (%s)", doc.id, label_exc)

            # 청크 하나만 봐서는 "이게 어느 문서(회사/제품) 얘기인지" 모를 수 있다 — 예를 들어
            # 회사명은 표지에만 있고, 본문 청크(용접 방식 설명 등)엔 회사명이 안 나오는 경우가 흔하다.
            # 그러면 "OO회사 용접방식은?" 같은 질문이 그 본문 청크와 잘 안 엮인다. 그래서 "이 문서가
            # 어디의 무엇인지"를 모든 청크 앞에 붙여서, 어느 청크든 자기가 속한 문서가 뭔지 임베딩에
            # 반영되게 한다. 문서에 붙은 라벨(여러 개일 수 있음)을 전부 이어붙이고, 하나도 없으면
            # 파일명으로 대체한다(파일명이 스캔 파일명처럼 의미 없는 경우엔 큰 도움은 안 되지만,
            # 그래도 아무 것도 없는 것보다는 낫다).
            labels_result = await session.execute(select(DocumentLabel.label).where(DocumentLabel.document_id == doc.id))
            labels = [row[0] for row in labels_result.all()]
            doc_title = ", ".join(labels) if labels else Path(doc.filename).stem
            title_prefix = f"[문서: {doc_title}]\n"
            for chunk in chunks:
                chunk.text = title_prefix + chunk.text
                if chunk.parent_text is not None:
                    chunk.parent_text = title_prefix + chunk.parent_text
                if chunk.precomputed_dense_vector is not None:
                    # 텍스트가 바뀌었으니 청킹 단계에서 미리 계산해둔 벡터는 더 이상 이 청크와 안 맞는다.
                    # 재사용하면 안 되므로 비워서, 임베딩 워커가 새 텍스트로 다시 계산하게 한다.
                    chunk.precomputed_dense_vector = None

            for chunk in chunks:
                table_confidence = compute_table_confidence(chunk.text)["confidence"] if chunk.is_table else None
                session.add(
                    DocumentChunk(
                        id=chunk.chunk_id,
                        document_id=doc.id,
                        text=chunk.text,
                        page_number=chunk.page_number,
                        is_table=chunk.is_table,
                        table_confidence=table_confidence,
                        image_path=chunk.image_path,
                        embedded=False,
                        precomputed_dense_vector=(
                            json.dumps(chunk.precomputed_dense_vector)
                            if chunk.precomputed_dense_vector is not None
                            else None
                        ),
                        parent_text=chunk.parent_text,
                    )
                )

            warnings = validate_chunks(doc.raw_text, chunks)
            doc.warning_message = " / ".join(warnings) if warnings else None
            if doc.warning_message:
                logger.warning("청킹 품질 경고: document_id=%s -> %s", doc.id, doc.warning_message)

            if intent_classifier is not None:
                try:
                    # 문서 앞부분(전체를 다 넣으면 임베딩 모델 입력 길이 제한에 걸릴 수 있어 앞부분만 사용)
                    classification = await intent_classifier.classify(doc.raw_text[:2000])
                    doc.category = classification[0]["category"]
                    doc.category_similarity = classification[0]["similarity"]
                    logger.info(
                        "의도 분류: document_id=%s -> %s (유사도 %.4f)", doc.id, doc.category, doc.category_similarity
                    )
                except Exception as classify_exc:  # noqa: BLE001
                    # 의도 분류는 부가 기능이라, 여기서 실패해도 청킹 자체(핵심 파이프라인)는 계속 진행시킨다.
                    logger.warning("의도 분류 실패(청킹은 정상 진행): document_id=%s (%s)", doc.id, classify_exc)

            doc.status = DocumentStatus.CHUNKED
            doc.retry_count = 0
            logger.info("청킹 완료: document_id=%s (%d개 청크)", doc.id, len(chunks))
        except Exception as exc:  # noqa: BLE001
            doc.retry_count += 1
            if doc.retry_count < settings.worker_max_retries:
                doc.error_message = f"[{doc.retry_count}/{settings.worker_max_retries}회 시도 실패, 자동 재시도 예정] {exc}"
                logger.warning(
                    "청킹 실패 (재시도 %d/%d): document_id=%s (%s)", doc.retry_count, settings.worker_max_retries, doc.id, exc
                )
            else:
                doc.status = DocumentStatus.FAILED
                doc.error_message = f"[{doc.retry_count}회 재시도 모두 실패] {exc}"
                logger.error("청킹 최종 실패 (재시도 %d회 소진): document_id=%s (%s)", doc.retry_count, doc.id, exc)

    await session.commit()
    return len(documents)


async def _reclassify_document_labels(doc: Document, embedding_provider, session: AsyncSession) -> None:
    """
    문서에 붙은 라벨(들)이 실제 내용과 잘 맞는지 하나씩 확인해서, 조용히 교정/제거한다
    (사용자에게 확인 안 물어봄).

    설계 배경 (사용자와 여러 차례 논의해서 확정):
      - "라벨끼리(예: 케이디은행 vs KD은행)" 비슷한 표기를 같은 것으로 잡아주는 건
        /api/document-labels/search의 자동완성(임베딩 검색)이 이미 담당한다. 거기서 후보로
        떴는데 사용자가 무시하고 새로 입력했다면, 그건 "신규로 받아들이겠다"는 의사표시로 본다.
      - 여기(청킹 단계, 문서 실제 내용 확보 후)서는 완전히 다른 문제를 본다 —
        "내용을 안 보고 대충/실수로 라벨을 붙인 경우"를 잡는 것. 두 갈래로 처리한다:
          1) 지금 라벨보다 확실히(LABEL_SWAP_MARGIN 이상) 더 잘 맞는 "기존" 라벨이 있으면 교체
          2) 그런 대안도 없고, 지금 라벨 자체가 내용과 절대적으로 안 맞으면(LABEL_ABSOLUTE_FLOOR
             미만) 그냥 라벨을 버린다 (대안 유무와 무관하게) — 사용자가 여러 파일을 한 번에
             묶어서 라벨을 대충 적용했을 때, 실제로 안 맞는 파일에 엉뚱한 라벨이 남는 걸 막는다.
      - 이 판단은 사람한테 매번 확인받지 않고 조용히 처리한다(사용자 요청 — 확인 절차 자체가
        귀찮음의 원인이라고 판단).
    """
    labels_result = await session.execute(select(DocumentLabel).where(DocumentLabel.document_id == doc.id))
    current_labels = list(labels_result.scalars().all())
    if not current_labels:
        return

    content_sample = doc.raw_text[:1000]
    content_vec = await embedding_provider.embed_query(content_sample)

    current_label_texts = {dl.label for dl in current_labels}
    other_labels_result = await session.execute(select(DocumentLabel.label).distinct())
    other_label_texts = [label for label in {row[0] for row in other_labels_result.all()} if label not in current_label_texts]
    other_vecs = await embedding_provider.embed_documents(other_label_texts) if other_label_texts else []
    other_map = dict(zip(other_label_texts, other_vecs))

    for doc_label in current_labels:
        label_vec = await embedding_provider.embed_query(doc_label.label)
        label_similarity = cosine_similarity(label_vec, content_vec)

        best_label, best_similarity = None, label_similarity
        for other_label, other_vec in other_map.items():
            similarity = cosine_similarity(other_vec, content_vec)
            if similarity > best_similarity + LABEL_SWAP_MARGIN:
                best_label, best_similarity = other_label, similarity

        if best_label is not None:
            logger.info(
                "라벨 자동 교체: document_id=%s, '%s'(유사도%.3f) -> '%s'(유사도%.3f)",
                doc.id,
                doc_label.label,
                label_similarity,
                best_label,
                best_similarity,
            )
            doc_label.label = best_label
        elif label_similarity < LABEL_ABSOLUTE_FLOOR:
            logger.info(
                "라벨 자동 제거(내용과 무관): document_id=%s, '%s'(유사도%.3f)", doc.id, doc_label.label, label_similarity
            )
            await session.delete(doc_label)


async def _generate_labels_via_llm(doc: Document, llm_provider) -> list[str]:
    """원문에 명시된 회사/모델/주제/공정/문서종류를 2~5개 라벨로 만든다."""
    sample = doc.raw_text[:2000]
    prompt = (
        "다음 문서에서 검색용 라벨을 2~5개 뽑으세요. 서로 다른 축을 사용하세요: "
        "(1) 원문에 명시된 회사/기관, (2) 제품명이나 정확한 모델명, (3) 핵심 주제·기능·공정, "
        "(4) 문서 종류. 원문에 없는 회사나 제품을 추측하지 마세요. ImageBox, Document, 이미지, "
        "문서처럼 내용 없는 라벨은 금지합니다. 짧은 문자열의 JSON 배열만 출력하세요.\n\n"
        f"문서 내용:\n{sample}"
    )
    try:
        raw = await llm_provider.generate(
            prompt=prompt,
            system_prompt="당신은 문서에 명시된 검색 메타데이터만 추출하는 도우미입니다.",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 라벨 생성 실패: document_id=%s (%s)", doc.id, exc)
        return []

    return parse_generated_labels(raw)


async def run_once() -> None:
    """standalone 실행 진입점. 청킹 전략(SemanticChunker 등)을 구체적으로 아는 곳은 여기뿐이다."""
    from ..core.bge_m3_provider import BgeM3EmbeddingProvider
    from ..core.qwen_ollama_provider import QwenOllamaProvider
    from ..core.structured_chunker import StructuredChunker
    from ..db.session import async_session_factory

    embedding_provider = BgeM3EmbeddingProvider()
    chunker: BaseChunker = StructuredChunker(embedding_provider=embedding_provider)
    intent_classifier = IntentClassifier(embedding_provider=embedding_provider)
    llm_provider = QwenOllamaProvider()

    async with async_session_factory() as session:
        n = await process_pending_documents(session, chunker, intent_classifier, embedding_provider, llm_provider)
        logger.info("이번 실행에서 %d개 문서 처리", n)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    asyncio.run(run_once())
