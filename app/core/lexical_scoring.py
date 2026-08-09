"""검색 후보에 대한 공통 키워드 겹침 점수 계산."""
from __future__ import annotations

import re
from collections.abc import Collection

_TOKEN_PATTERN = re.compile(r"[0-9a-z가-힣]+(?:[./_-][0-9a-z가-힣]+)*", re.IGNORECASE)
_STOPWORDS = {
    "그", "및", "또는", "그리고", "대한", "대해", "관련", "무엇", "무엇인가",
    "뭐", "어떻게", "알려줘", "설명", "설명해줘", "인가", "인가요", "해줘",
}
_KOREAN_SUFFIXES = (
    "으로부터", "에게서", "에서는", "으로는", "에서", "에게", "까지", "부터",
    "으로", "라고", "이라는", "의", "은", "는", "이", "가", "을", "를", "에",
    "로", "와", "과", "도", "만",
)


def _normalize_token(token: str) -> str:
    token = token.casefold()
    for suffix in _KOREAN_SUFFIXES:
        if token.endswith(suffix) and len(token) >= len(suffix) + 2:
            return token[: -len(suffix)]
    return token


def query_terms(query: str) -> list[str]:
    """질문에서 조사와 상투적 질문어를 제거한 검색 핵심어를 만든다."""
    terms: list[str] = []
    for raw in _TOKEN_PATTERN.findall(query):
        term = _normalize_token(raw)
        if len(term) < 2 or term in _STOPWORDS or term in terms:
            continue
        terms.append(term)
    return terms


def keyword_overlap_score(terms: Collection[str], text: str) -> float:
    """미리 추출한 핵심어 중 후보 텍스트에 등장하는 가중 비율(0~1)."""
    if not terms:
        return 0.0

    matched_terms = match_query_terms(terms, text)
    weighted_terms = [(term, max(1.0, min(3.0, len(term) / 2))) for term in terms]
    matched = sum(weight for term, weight in weighted_terms if term in matched_terms)
    return matched / sum(weight for _, weight in weighted_terms)


def match_query_terms(terms: Collection[str], text: str) -> set[str]:
    """공백을 무시했을 때 텍스트에 실제로 등장한 질문 핵심어 집합."""
    normalized_text = re.sub(r"\s+", "", text.casefold())
    return {term for term in terms if term in normalized_text}
