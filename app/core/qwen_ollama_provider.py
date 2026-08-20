"""
Qwen2.5(Ollama 서빙) LLM Provider 구현체.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator

import httpx

from ..config import settings
from .llm_provider import BaseLLMProvider

logger = logging.getLogger(__name__)

_THINK_BLOCK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_CLOSE = "</think>"


async def _strip_think_stream(tokens: AsyncIterator[str]) -> AsyncIterator[str]:
    """모델 내부 사고 과정을 걸러내고 최종 답변만 내보낸다.

    "think": false와 프롬프트 끝 "/no_think"를 모두 보내도 이 Ollama/qwen3 조합은
    사고 과정을 그대로 내보내며, 심지어 여는 태그(<think>) 없이 닫는 태그(</think>)만
    남기는 경우가 있어 태그 쌍 매칭이나 실시간 스트리밍 필터로는 걸러낼 수 없었다
    (실측 확인됨). 그래서 토큰이 나오는 대로 바로 흘려보내지 않고 전체 응답을 모은
    뒤 사고 과정으로 보이는 구간을 제거하고 한 번에 내보낸다 — 타이핑 효과는 없어지지만
    화면에 영어 추론 원문이 새는 문제를 확실히 막는다.
    """
    parts = [token async for token in tokens]
    full_text = "".join(parts)
    cleaned = _THINK_BLOCK_PATTERN.sub("", full_text)
    close_idx = cleaned.find(_THINK_CLOSE)
    if close_idx != -1:
        # 여는 태그 없이 닫는 태그만 남은 경우 — 그 앞부분도 전부 사고 과정이다.
        cleaned = cleaned[close_idx + len(_THINK_CLOSE):]
    cleaned = cleaned.strip()
    if cleaned:
        yield cleaned


def _normalize_ollama_model_name(name: str) -> str:
    """Ollama 모델명을 비교 가능한 ``name:tag`` 형태로 정규화한다."""
    normalized = name.strip().lower().split("@", 1)[0]
    if normalized and ":" not in normalized.rsplit("/", 1)[-1]:
        normalized = f"{normalized}:latest"
    return normalized


def ollama_model_is_available(payload: dict, requested_model: str) -> bool:
    """``/api/tags`` 응답에 설정된 모델이 실제로 설치되어 있는지 확인한다."""
    requested = _normalize_ollama_model_name(requested_model)
    available: set[str] = set()
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                available.add(_normalize_ollama_model_name(value))
    return requested in available


class QwenOllamaProvider(BaseLLMProvider):
    """Ollama에 로컬 서빙된 Qwen2.5를 호출하는 LLM Provider"""

    def __init__(self) -> None:
        self._base_url = settings.llm_provider_base_url
        self._model = settings.llm_model_name

    def _payload(self, prompt: str, system_prompt: str | None, stream: bool) -> dict:
        # Ollama의 "think" 파라미터는 이 서버/모델 조합에서 무시되고, 그 결과 <think> 태그도 없이
        # 영어 사고 과정이 답변에 그대로 섞여 나오는 문제가 있었다(관측 확인 완료).
        # Qwen3는 프롬프트 끝의 "/no_think" 지시를 자체적으로 인식해 사고 과정을 생략하므로,
        # think 옵션이 무시되는 환경에서도 이 방식은 안정적으로 동작한다.
        effective_prompt = prompt if settings.llm_think else f"{prompt}\n\n/no_think"
        return {
            "model": self._model,
            "prompt": effective_prompt,
            "system": system_prompt,
            "stream": stream,
            "think": settings.llm_think,
            "keep_alive": settings.llm_keep_alive,
            "options": {
                "temperature": settings.llm_temperature,
                "top_p": settings.llm_top_p,
                "num_ctx": settings.llm_num_ctx,
                "num_predict": settings.llm_num_predict,
            },
        }

    async def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """답변을 한 번에 반환한다."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=300.0) as client:
            response = await client.post("/api/generate", json=self._payload(prompt, system_prompt, False))
            response.raise_for_status()
            data = response.json()
            answer = str(data.get("response", ""))
            return _THINK_BLOCK_PATTERN.sub("", answer).strip()

    async def generate_stream(self, prompt: str, system_prompt: str | None = None) -> AsyncIterator[str]:
        """답변을 토큰 단위(NDJSON 라인 단위)로 스트리밍한다. <think> 구간은 걸러서 내보낸다."""
        async for token in _strip_think_stream(self._raw_generate_stream(prompt, system_prompt)):
            yield token

    async def _raw_generate_stream(
        self, prompt: str, system_prompt: str | None = None
    ) -> AsyncIterator[str]:
        async with httpx.AsyncClient(base_url=self._base_url, timeout=300.0) as client:
            async with client.stream(
                "POST",
                "/api/generate",
                json=self._payload(prompt, system_prompt, True),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("response", "")
                    if token:
                        yield token
                    if chunk.get("done"):
                        break

    async def ping(self) -> None:
        """Ollama 서버와 설정된 LLM 모델의 설치 상태를 함께 확인한다."""
        async with httpx.AsyncClient(base_url=self._base_url, timeout=5.0) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            if not ollama_model_is_available(response.json(), self._model):
                raise RuntimeError(
                    f"Ollama 모델이 설치되어 있지 않습니다: {self._model}. "
                    f"`docker compose exec ollama ollama pull {self._model}`을 실행하세요."
                )

    async def unload(self) -> None:
        """메타데이터 생성 뒤 Ollama 모델을 내려 다음 GPU 단계에 VRAM을 양보한다."""
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=60.0) as client:
                response = await client.post(
                    "/api/generate",
                    json={"model": self._model, "prompt": "", "stream": False, "keep_alive": 0},
                )
                response.raise_for_status()
            logger.info("Ollama LLM 언로드 완료: %s", self._model)
        except Exception as exc:  # noqa: BLE001
            # 언로드 최적화 실패가 문서 파이프라인 자체를 중단시키면 안 된다.
            logger.warning("Ollama LLM 언로드 실패(임베딩은 계속 진행): %s", exc)


def build_cross_lingual_system_prompt(question_language: str, answer_language: str = "ko") -> str:
    """
    교차언어 대응용 system_prompt를 만든다.
    질문/검색된 문서 언어가 다르더라도, 지정된 answer_language로 답변하도록 명시적으로 지시한다.
    """
    return (
        f"사용자의 질문 언어는 '{question_language}'이지만, 반드시 '{answer_language}' 언어로 답변하세요. "
        "제공된 컨텍스트가 다른 언어(예: 영어, 중국어 등)로 되어 있어도 정확히 이해하고 "
        f"'{answer_language}'로 자연스럽게 번역/요약해서 답변하세요."
    )
