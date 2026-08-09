"""
BAAI/bge-m3 임베딩 구현체.

- dense 벡터: 일반적인 코사인 유사도 기반 벡터 검색용
- sparse 벡터: BM25류 키워드 매칭을 대체하는 lexical weight (하이브리드 검색용)

모델 로딩 비용이 크므로 프로세스 시작 시 한 번만 인스턴스를 생성해서 재사용해야 한다
(예: FastAPI lifespan에서 싱글턴으로 관리).

동기 라이브러리(FlagEmbedding)를 asyncio.to_thread로 감싸서 이벤트 루프를 막지 않도록 처리했다.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings
from .embeddings import BaseEmbeddingProvider

logger = logging.getLogger(__name__)


class BgeM3EmbeddingProvider(BaseEmbeddingProvider):
    """FlagEmbedding의 BGEM3FlagModel을 사용하는 임베딩 구현체"""

    def __init__(self) -> None:
        try:
            from FlagEmbedding import BGEM3FlagModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "FlagEmbedding 패키지가 설치되어 있지 않습니다. requirements.txt를 확인하세요."
            ) from exc

        import torch

        self._use_cuda = bool(settings.embedding_use_gpu and torch.cuda.is_available())
        if settings.embedding_use_gpu and not self._use_cuda:
            logger.warning("EMBEDDING_USE_GPU=true이지만 CUDA PyTorch가 없어 bge-m3를 CPU로 실행합니다.")
        logger.info("bge-m3 모델 로딩 시작 (경로: %s, device=%s)", settings.embedding_model_dir, "cuda" if self._use_cuda else "cpu")
        self._model = BGEM3FlagModel(
            settings.embedding_model_dir,
            use_fp16=self._use_cuda,  # CPU에서 fp16을 강제하면 지원하지 않는 연산이 생길 수 있음
            device="cuda" if self._use_cuda else "cpu",
        )
        logger.info("bge-m3 모델 로딩 완료")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """문서(청크) 목록을 dense 벡터로 변환한다."""
        result = await self._encode_with_retry(texts, return_dense=True, return_sparse=False, return_colbert_vecs=False)
        return result["dense_vecs"].tolist()

    async def _encode_with_retry(self, texts: list[str], **encode_kwargs):
        """
        GPU 메모리 부족(OOM) 상황에서 FlagEmbedding 내부의 배치 축소 재시도 로직이
        배치 크기 1(질문 하나 등)일 때 0까지 줄어들어 IndexError로 깨지는 버그가 있다.
        여기서 한 번 더 감싸서, 실패하면 CUDA 캐시를 비우고 딱 한 번만 재시도한다.
        """
        try:
            return await asyncio.to_thread(self._model.encode, texts, **encode_kwargs)
        except (IndexError, RuntimeError) as exc:
            logger.warning("임베딩 실패(GPU 메모리 부족으로 추정), 캐시 비우고 재시도: %s", exc)
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
            return await asyncio.to_thread(self._model.encode, texts, **encode_kwargs)

    async def embed_query(self, text: str) -> list[float]:
        """검색 질의 하나를 dense 벡터로 변환한다. bge-m3는 query/document 벡터 공간이 동일하다."""
        vectors = await self.embed_documents([text])
        return vectors[0]

    async def embed_hybrid(self, texts: list[str]) -> tuple[list[list[float]], list[dict[int, float]]]:
        """BGE-M3 모델을 한 번만 통과시켜 dense와 sparse를 동시에 얻는다."""
        result = await self._encode_with_retry(
            texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = result["dense_vecs"].tolist()
        sparse = [
            {int(token_id): weight for token_id, weight in item.items()}
            for item in result["lexical_weights"]
        ]
        return dense, sparse

    def count_tokens(self, text: str) -> int:
        """
        bge-m3가 실제로 쓰는 토크나이저로 진짜 토큰 개수를 센다.
        (예전엔 "한국어는 토큰당 대략 2자"로 근사했는데, 실제 서브워드 토크나이저는 이 근사와
        꽤 어긋날 수 있어서 — 특히 영어/숫자/특수문자 섞인 텍스트에서 — 정확도를 위해 실측으로 바꿨다.)
        인코딩(임베딩 계산) 없이 토크나이즈만 하는 거라 빠르다.
        """
        return len(self._model.tokenizer.encode(text, add_special_tokens=False))
