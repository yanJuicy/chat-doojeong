"""
Ollama에 로컬 서빙된 Vision-LLM(Qwen2-VL 등)으로 이미지 캡션을 생성하는 구현체.
표 추출 모듈(vlm_engine.py)과 동일한 호출 패턴(base64 인코딩 + Ollama /api/generate)을 쓴다.
"""
from __future__ import annotations

import base64
import io
import logging

import httpx
from PIL import Image

from ..config import settings
from .image_captioner import BaseImageCaptioner

logger = logging.getLogger(__name__)

_CAPTION_PROMPT_BASE = (
    "Convert this image into searchable plain text using only facts visible in the image. "
    "Capture the title, product or subject, functions, numbers, labels, and relationships. "
    "If there is a numbered diagram or process flow, follow the visual number order and list every step as '1. ...'. "
    "Copy clear Korean labels exactly; English explanations are acceptable. Do not guess a company, product, or function. "
    "Return 4-12 concise lines without markdown tables."
)
_CAPTION_PROMPT_WITH_CONTEXT_TEMPLATE = (
    "{base_prompt}\n\n"
    "참고로 이 이미지는 아래 문맥(같은 페이지의 주변 텍스트)과 함께 등장했습니다. "
    "이미지 안에 실제로 보이는 내용을 우선 설명하되, 이 문맥이 이미지의 의미를 이해하는 데 "
    "도움이 된다면 반영해서 설명하세요 (예: 같은 그림이라도 문맥에 따라 어떤 통계/개념을 나타내는지 다르게 짚어줄 것).\n\n"
    "--- 주변 문맥 ---\n{context}\n--- 문맥 끝 ---"
)


class OllamaVisionCaptioner(BaseImageCaptioner):
    """Ollama Vision-LLM(예: qwen2-vl) 기반 이미지 캡셔너"""

    def __init__(self) -> None:
        self._base_url = settings.vlm_provider_base_url
        self._model = settings.vlm_model_name

    async def caption(self, image: Image.Image, context: str = "") -> str:
        """
        이미지를 Vision-LLM에 전달해 한국어 캡션을 생성한다. 실패 시 빈 문자열을 반환한다.
        context가 주어지면 프롬프트에 같이 넣어서, 같은 이미지라도 등장 문맥에 따라
        다르게 설명될 수 있도록 한다 (그래서 이 결과는 캐싱하면 안 된다 — 문맥마다 새로 호출해야 함).
        """
        image_b64 = self._encode_image(image)
        prompt = (
            _CAPTION_PROMPT_WITH_CONTEXT_TEMPLATE.format(base_prompt=_CAPTION_PROMPT_BASE, context=context.strip()[:800])
            if context.strip()
            else _CAPTION_PROMPT_BASE
        )
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=180.0) as client:
                response = await client.post(
                    "/api/chat",
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "user", "content": prompt, "images": [image_b64]}
                        ],
                        "stream": False,
                        "think": False,
                        "keep_alive": settings.vlm_keep_alive,
                        "options": {"temperature": 0.05, "num_ctx": 4096, "num_predict": 384},
                    },
                )
                response.raise_for_status()
                data = response.json()
                if not data.get("done", False):
                    logger.warning("VLM이 불완전 응답을 반환해 캡션을 폐기합니다: %s", data)
                    return ""
                return str(data.get("message", {}).get("content", "")).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("이미지 캡션 생성 실패, 빈 캡션으로 대체: %s", exc)
            return ""

    @staticmethod
    def _encode_image(image: Image.Image) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
