"""LLM 응답을 검증된 업무 초안으로 변환한다."""

from __future__ import annotations

import json

from pydantic import ValidationError

from ...core.llm_provider import BaseLLMProvider
from .models import NaturalWorkEntryRequest, NaturalWorkEntryResponse
from .prompts import SYSTEM_PROMPT, build_extraction_prompt


class WorkEntryExtractionError(RuntimeError):
    pass


def _extract_json_object(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1]).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise WorkEntryExtractionError("LLM 응답에서 JSON 객체를 찾지 못했습니다.")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise WorkEntryExtractionError("LLM이 유효하지 않은 JSON을 반환했습니다.") from exc
    if not isinstance(payload, dict):
        raise WorkEntryExtractionError("LLM 응답은 JSON 객체여야 합니다.")
    return payload


class NaturalWorkEntryExtractor:
    def __init__(self, llm_provider: BaseLLMProvider) -> None:
        self._llm_provider = llm_provider

    async def extract(self, request: NaturalWorkEntryRequest) -> NaturalWorkEntryResponse:
        raw = await self._llm_provider.generate(
            prompt=build_extraction_prompt(request.text, request.reference_date),
            system_prompt=SYSTEM_PROMPT,
        )
        payload = _extract_json_object(raw)
        items = payload.get("items", [])
        if isinstance(items, list):
            items = [
                {**item, "author": request.author, "department": request.department}
                if isinstance(item, dict)
                else item
                for item in items
            ]
        try:
            response = NaturalWorkEntryResponse(
                drafts=items,
                warnings=payload.get("warnings", []),
                requires_confirmation=True,
            )
        except ValidationError as exc:
            raise WorkEntryExtractionError("LLM 응답이 업무 데이터 규격과 맞지 않습니다.") from exc
        if not response.drafts:
            response.warnings.append("저장할 수 있는 업무를 찾지 못했습니다.")
        return response
