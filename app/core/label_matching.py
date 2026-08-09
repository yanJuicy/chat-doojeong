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

_ORGANIZATION_SUFFIXES = tuple(
    sorted(
        {
            "메카트로닉스",
            "테크놀로지",
            "로보틱스",
            "자동화",
            "연구소",
            "시스템",
            "솔루션",
            "열관리",
            "이동체",
            "테크",
            "정밀",
            "전자",
            "전기",
            "산업",
            "소재",
            "기술",
        },
        key=len,
        reverse=True,
    )
)
_COMPARISON_CUES = ("두 ", "둘 ", "비교", "차이", "중 ", "각각", "더 긴", "더 큰", "더 작은")


def normalize_label_match_text(value: str) -> str:
    normalized = value.casefold()
    for source, target in _CANONICAL_TERMS.items():
        normalized = normalized.replace(source, target)
    return re.sub(r"[^0-9a-z가-힣]+", "", normalized)


def organization_label_aliases(label: str) -> set[str]:
    """회사형 라벨에서 질문에 자연스럽게 쓰이는 짧은 상호 별칭을 만든다.

    임의 앞글자 두 글자를 허용하지 않고 알려진 조직 접미사가 실제로 붙은 경우만
    제거한다. 두 글자 미만 별칭은 오탐 위험이 커서 사용하지 않는다.
    """
    normalized = normalize_label_match_text(label)
    aliases: set[str] = set()
    for suffix in _ORGANIZATION_SUFFIXES:
        normalized_suffix = normalize_label_match_text(suffix)
        if normalized.endswith(normalized_suffix):
            alias = normalized[: -len(normalized_suffix)]
            if len(alias) >= 2:
                aliases.add(alias)
    return aliases


def model_family_aliases(label: str) -> set[str]:
    """VTX-310/VTX-310E처럼 숫자 앞의 3자 이상 영문 모델 계열명을 반환한다."""
    normalized = normalize_label_match_text(label)
    match = re.match(r"^([a-z]{3,})(?=\d)", normalized)
    return {match.group(1)} if match else set()


def find_question_label_hints(question: str, labels: list[str]) -> list[str]:
    """완전일치 라벨과 충돌하지 않는 회사 별칭 라벨을 찾는다."""
    normalized_question = normalize_label_match_text(question)
    exact_matches = {
        label
        for label in labels
        if (normalized_label := normalize_label_match_text(label)) and normalized_label in normalized_question
    }

    question_tokens = {
        normalize_label_match_text(token)
        for token in re.findall(r"[0-9a-z가-힣]+", question.casefold())
        if normalize_label_match_text(token)
    }
    alias_owners: dict[str, set[str]] = {}
    for label in labels:
        for alias in organization_label_aliases(label):
            alias_owners.setdefault(alias, set()).add(label)

    alias_matches = {
        next(iter(owners))
        for alias, owners in alias_owners.items()
        if alias in question_tokens and len(owners) == 1
    }

    family_matches: set[str] = set()
    if any(cue in question.casefold() for cue in _COMPARISON_CUES):
        family_owners: dict[str, set[str]] = {}
        for label in labels:
            for family in model_family_aliases(label):
                family_owners.setdefault(family, set()).add(label)
        for family, owners in family_owners.items():
            if family in question_tokens and len(owners) >= 2:
                family_matches.update(owners)

    return sorted(exact_matches | alias_matches | family_matches, key=len, reverse=True)


def label_is_question_hint(question: str, label: str) -> bool:
    """라벨이 질문에 직접 또는 허용된 동의표현으로 등장하는지 확인한다."""
    return bool(find_question_label_hints(question, [label]))


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
