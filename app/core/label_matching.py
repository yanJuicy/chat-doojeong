"""질문 표현과 문서 라벨의 보수적인 표기 차이를 정규화한다."""
from __future__ import annotations

import re

_CANONICAL_TERMS = {
    "과정": "공정",
    "절차": "공정",
    "사용법": "사용방법",
    "활용법": "사용방법",
    "쓰는법": "사용방법",
    "방법": "방식",
    "용도": "기능",
    "역할": "기능",
}

_QUERY_EXPANSIONS = {
    "과정": ("공정", "절차"),
    "공정": ("과정", "절차"),
    "절차": ("과정", "공정"),
    "사용법": ("사용방법", "사용 방식"),
    "활용법": ("활용 방법", "사용방법"),
    "용도": ("기능", "역할"),
    "기능": ("역할", "용도"),
    "역할": ("기능", "용도"),
    "사양": ("제원", "스펙"),
    "제원": ("사양", "스펙"),
}


def normalize_label_match_text(value: str) -> str:
    normalized = value.casefold()
    for source, target in _CANONICAL_TERMS.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized)


def label_is_question_hint(question: str, label: str) -> bool:
    """라벨이 질문에 직접 또는 허용된 동의표현으로 등장하는지 확인한다."""
    normalized_label = normalize_label_match_text(label)
    normalized_question = normalize_label_match_text(question)
    return bool(normalized_label) and normalized_label in normalized_question


def expand_search_query(question: str) -> str:
    """원문은 보존하고, 문서에서 흔히 쓰는 동의표현만 뒤에 덧붙인다."""
    additions: list[str] = []
    for source, alternatives in _QUERY_EXPANSIONS.items():
        if source in question:
            additions.extend(alternative for alternative in alternatives if alternative not in question)
    if not additions:
        return question
    unique_additions = list(dict.fromkeys(additions))
    return f"{question} {' '.join(unique_additions)}"
