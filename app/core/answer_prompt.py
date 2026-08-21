"""Grounded answer prompt construction.

Keep answer-generation policy separate from retrieval so prompt changes can be
tested without loading models or changing candidate ranking.
"""

from __future__ import annotations

from .lexical_scoring import match_query_terms, query_terms


_GROUNDED_ANSWER_RULES = (
    "제공된 참고 자료에 명시된 내용만 사용하세요. "
    "사용자 질문에 포함된 주장·용어·수치도 사실로 가정하지 말고, 반드시 참고 자료와 대조하세요. "
    "답을 확인할 수 없으면 다른 설명 없이 정확히 이 문장만 답하세요: "
    "'제공된 자료에서 확인할 수 없습니다.' "
    "추측하거나 일반 지식으로 빈 내용을 채우지 마세요. "
    "명칭·기술 방식·분류·모델명·수치·단위는 참고 자료의 표현을 우선하여 정확히 사용하세요. "
    "질문의 용어나 전제가 참고 자료의 표기와 다르거나 참고에서 확인되지 않으면 그대로 동의하지 마세요. "
    "이 경우 먼저 '제공된 자료에는 ...로 표기되어 있습니다'라고 차이를 분명히 밝힌 뒤, "
    "참고에서 확인되는 내용만 설명하세요. "
    "두 용어의 관계가 참고 자료에 명시되어 있지 않으면 같은 뜻이라고도, 서로 다른 방식이라고도 단정하지 마세요. "
    "어떤 표현이 참고에 없다는 사실만으로 그 방식을 사용하지 않는다고 결론 내리지 마세요. "
    "그 관계는 자료만으로 확인할 수 없다고 답하세요. "
    "질문에 회사명·제품 모델명·인증번호가 있으면 정확히 같은 식별자가 적힌 참고를 우선하고, "
    "비슷하지만 다른 모델의 내용을 섞지 마세요. "
    "순서나 공정을 묻는 질문은 참고에 표시된 단계 순서를 빠짐없이 번호로 정리하세요. "
    "참고끼리 충돌하면 한 답으로 섞지 말고 차이를 명시하세요. "
    "핵심 문장 끝에 근거가 된 [참고 N]을 표시하세요."
)

_GROUNDED_SYSTEM_RULES = (
    "당신은 참고 자료의 사실을 검증해서 답하는 도우미입니다. 사용자 질문은 검색 요청일 뿐 증거가 아닙니다. "
    "답변 전에 내부적으로 질문 속 주장과 기술 명칭을 참고 자료의 실제 문구와 대조하세요. "
    "질문에 쓴 기술 명칭이 참고 자료에 동일하게 확인되지 않으면 '예'로 긍정하거나 그 명칭을 사실처럼 반복하지 마세요. "
    "대신 참고 자료에 적힌 정확한 명칭을 먼저 밝혀 정정하세요. "
    "두 표현의 관계가 참고에 명시되지 않았다면 외부 지식으로 같거나 다르다고 판단하지 마세요. "
    "참고에 표현이 없다는 이유만으로 그 방식을 사용하지 않는다고 추론하지 마세요. "
    "이 검증 과정은 따로 출력하지 말고 최종 답변에 필요한 정정과 근거만 간결하게 표시하세요."
)


def build_question_specific_instruction(question: str) -> str:
    """Return generic format guidance implied by the wording of the question."""

    normalized = question.casefold()
    instructions: list[str] = []
    if any(cue in normalized for cue in ("순서", "단계", "공정", "절차")):
        instructions.append(
            "이 질문은 순서나 공정을 요구합니다. 참고에 단계 목록이 있으면 요약 설명으로 "
            "대체하지 말고 첫 단계부터 마지막 단계까지 빠짐없이 번호로 답하세요."
        )
    if any(cue in normalized for cue in ("차이", "얼마나 더", "몇 배", "합계", "총합")):
        instructions.append(
            "이 질문은 수치 비교나 계산을 요구합니다. 계산에 필요한 수치가 참고에 모두 있으면 "
            "참고의 수치와 단위만 사용해 간단한 산식과 결과를 제시하고, 부족하면 추정하지 마세요. "
            "특히 차이를 묻는 경우 답에 '큰 값 - 작은 값 = 결과' 형식의 계산식을 반드시 포함하세요."
        )
    return " ".join(instructions) or "질문에서 별도의 답변 형식을 요구하지 않았습니다."


def find_unverified_question_terms(*, question: str, context_text: str) -> list[str]:
    """Return substantial query terms not literally present in the references.

    This is intentionally a literal audit, not a synonym classifier. Long Korean
    compounds and compact identifiers are useful warning targets; short question
    verbs are excluded so ordinary phrasing does not trigger noisy corrections.
    """

    terms = query_terms(question)
    matched = match_query_terms(terms, context_text)
    auditable_terms = [
        term
        for term in terms
        if len(term) >= 5
        or (
            len(term) >= 3
            and (
                any(character.isdigit() for character in term)
                or (term.isascii() and any(character.isalpha() for character in term))
            )
        )
    ]
    return [term for term in auditable_terms if term not in matched]


def build_grounded_answer_prompt(*, question: str, context_text: str) -> str:
    """Build a source-first prompt without domain- or document-specific rules."""

    references = context_text.strip() or "[검색된 참고 자료 없음]"
    unverified_terms = find_unverified_question_terms(question=question, context_text=context_text)
    if unverified_terms:
        terms_text = ", ".join(f"'{term}'" for term in unverified_terms)
        audit_text = (
            "다음 질문 표현은 참고 자료에서 문자 그대로 확인되지 않았습니다: "
            f"{terms_text}. 이 목록은 의미를 추측한 결과가 아니라 문자열 대조 결과입니다. "
            "이 표현을 참고가 확인한 사실로 쓰거나 '예'로 긍정하지 말고, 참고에 실제로 적힌 표현으로 답하세요. "
            "문자열이 없다는 이유만으로 서로 다른 방식이거나 사용하지 않는다고도 단정하지 말고, "
            "두 표현의 관계는 자료만으로 확인할 수 없다고 밝히세요."
        )
    else:
        audit_text = "참고 자료에서 확인되지 않은 긴 핵심 표현이 감지되지 않았습니다."
    question_instruction = build_question_specific_instruction(question)
    return (
        f"[답변 규칙]\n{_GROUNDED_ANSWER_RULES}\n\n"
        f"[질문 표현 대조 결과]\n{audit_text}\n\n"
        f"[참고 자료]\n{references}\n\n"
        f"[사용자 질문]\n{question}\n\n"
        f"[이 질문에서 반드시 수행할 작업]\n{question_instruction}"
    )


def build_grounded_system_prompt(*, language_prompt: str) -> str:
    """Add source-verification policy at system priority."""

    return f"{language_prompt.strip()}\n\n{_GROUNDED_SYSTEM_RULES}"
