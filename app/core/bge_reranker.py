"""
BAAI/bge-reranker-v2-m3 구현체 (Cross-encoder 기반 정밀 재정렬).

1차 검색(Qdrant+bge-m3)에서 넉넉히 뽑은 후보를 query와 1:1로 다시 비교해서
연관도 점수를 재계산하고 상위 top_k개만 남긴다.
"""
from __future__ import annotations

import asyncio
import gc
import logging
from collections.abc import Collection

from ..config import settings
from .lightweight_reranker import lightweight_rerank
from .reranker import BaseReranker
from .vector_store import SearchResult

logger = logging.getLogger(__name__)


class BgeRerankerV2(BaseReranker):
    """FlagEmbedding의 FlagReranker를 사용하는 리랭커 구현체"""

    def __init__(self) -> None:
        import torch

        self._torch = torch
        self._rerank_lock = asyncio.Lock()
        self._use_cuda = bool(settings.embedding_use_gpu and torch.cuda.is_available())
        self._model = None
        if settings.embedding_use_gpu and not self._use_cuda:
            logger.warning(
                "EMBEDDING_USE_GPU=true이지만 CUDA PyTorch가 없어 대형 리랭커를 로드하지 않고 "
                "경량 하이브리드 재정렬을 사용합니다."
            )
            return

        try:
            from FlagEmbedding import FlagReranker  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "FlagEmbedding 패키지가 설치되어 있지 않습니다. requirements.txt를 확인하세요."
            ) from exc
        logger.info("bge-reranker-v2-m3 모델 로딩 시작 (경로: %s, device=%s)", settings.reranker_model_dir, "cuda" if self._use_cuda else "cpu")
        self._model = FlagReranker(
            settings.reranker_model_dir,
            use_fp16=self._use_cuda,
            devices="cuda" if self._use_cuda else "cpu",
        )
        logger.info("bge-reranker-v2-m3 모델 로딩 완료")

    @property
    def using_cuda(self) -> bool:
        """실제 리랭커 실행 장치. 환경설정 문자열이 아니라 PyTorch 가용성 기준이다."""
        return self._use_cuda

    async def rerank(
        self,
        query: str,
        candidates: list[SearchResult],
        top_k: int = 5,
        preferred_document_ids: Collection[str] = (),
    ) -> list[SearchResult]:
        """Cross-encoder로 재정렬하고 CUDA OOM이면 경량 리랭커로 폴백한다."""
        if not candidates:
            return []

        # 단일 모델의 동시 CUDA 실행을 막아 순간 VRAM 사용량이 겹치지 않게 한다.
        async with self._rerank_lock:
            if self._model is None:
                return lightweight_rerank(query, candidates, preferred_document_ids)[:top_k]

            pairs = [[query, candidate.text] for candidate in candidates]
            try:
                scores = await asyncio.to_thread(self._model.compute_score, pairs, normalize=True)
            except RuntimeError as exc:
                if not self._is_cuda_oom(exc):
                    raise
                logger.exception(
                    "CUDA OOM으로 대형 리랭커를 비활성화하고 경량 리랭커로 폴백합니다. 후보=%d",
                    len(candidates),
                )
                self._disable_after_cuda_oom()
                return lightweight_rerank(query, candidates, preferred_document_ids)[:top_k]

        # candidates가 1개뿐이면 compute_score가 float 하나만 반환하는 경우가 있어 리스트로 통일
        if isinstance(scores, float):
            scores = [scores]

        rescored = [
            candidate.model_copy(update={"score": float(score)}) for candidate, score in zip(candidates, scores)
        ]
        rescored.sort(key=lambda r: r.score, reverse=True)

        logger.info("리랭킹 완료: 후보 %d개 -> 상위 %d개", len(candidates), min(top_k, len(rescored)))
        return rescored[:top_k]

    def _is_cuda_oom(self, exc: RuntimeError) -> bool:
        if not self._use_cuda:
            return False
        oom_type = getattr(self._torch.cuda, "OutOfMemoryError", None)
        return bool(
            (oom_type is not None and isinstance(exc, oom_type))
            or "cuda out of memory" in str(exc).casefold()
        )

    def _disable_after_cuda_oom(self) -> None:
        """OOM이 난 모델 참조를 해제하고 이후 요청을 경량 경로로 보낸다."""
        model = self._model
        self._model = None
        self._use_cuda = False
        del model
        gc.collect()
        try:
            self._torch.cuda.empty_cache()
        except Exception:
            logger.warning("CUDA OOM 후 캐시 정리에 실패했습니다.", exc_info=True)
