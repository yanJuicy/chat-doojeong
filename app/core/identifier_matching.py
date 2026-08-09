"""모델명·인증번호처럼 철자가 중요한 식별자를 검색 점수에 반영한다."""
from __future__ import annotations

import re

from .vector_store import SearchResult

_IDENTIFIER_PATTERN = re.compile(r"(?=[A-Z0-9-]{4,})(?=[A-Z0-9-]*[A-Z])(?=[A-Z0-9-]*\d)[A-Z0-9]+(?:-[A-Z0-9]+)+|[A-Z]{1,8}\d[A-Z0-9-]{2,}", re.IGNORECASE)


def extract_identifiers(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _IDENTIFIER_PATTERN.finditer(text)}


def boost_exact_identifiers(results: list[SearchResult], question: str, weight: float) -> None:
    """질문의 영숫자 식별자가 후보 본문에 그대로 있으면 오프라인으로 안전하게 가산한다."""
    identifiers = extract_identifiers(question)
    if not identifiers or weight <= 0:
        return
    for result in results:
        candidate_text = result.text.casefold()
        matched = sum(1 for identifier in identifiers if identifier in candidate_text)
        if matched:
            result.score = min(1.0, result.score + weight * matched)
    results.sort(key=lambda result: result.score, reverse=True)
