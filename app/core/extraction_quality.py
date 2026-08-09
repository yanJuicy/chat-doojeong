"""OCR/텍스트 추출 결과가 검색에 넣을 만한지 가볍게 판정하는 품질 게이트."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_CONTENT_CHAR = re.compile(r"[0-9A-Za-z가-힣一-龥]")
_WORD = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_HANGUL = re.compile(r"[가-힣]")
_HANJA = re.compile(r"[一-龥]")
_REPEATED_PUNCT = re.compile(r"([^\w\s])\1{3,}")
_HTML_TAG = re.compile(r"<[^>]*>", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


@dataclass(frozen=True)
class ExtractionQuality:
    score: float
    char_count: int
    content_char_ratio: float
    word_count: int
    unique_word_ratio: float
    hanja_to_korean_ratio: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_extraction_quality(text: str) -> ExtractionQuality:
    """길이만 보지 않고 문자 밀도·단어 다양성·깨진 한자 비율을 함께 평가한다."""
    # OCR 본문이 아니라 PPStructure가 생성한 HTML/이미지 경로가 길이와 단어 수를
    # 부풀리지 않도록 품질 계산에서 마크업을 제외한다.
    scoring_text = _HTML_COMMENT.sub(" ", text or "")
    scoring_text = _HTML_TAG.sub(" ", scoring_text)
    scoring_text = _MARKDOWN_IMAGE.sub(" ", scoring_text)
    normalized = " ".join(scoring_text.split())
    char_count = len(normalized)
    if not normalized:
        return ExtractionQuality(0.0, 0, 0.0, 0, 0.0, 0.0, ["추출된 텍스트가 비어 있음"])

    content_chars = len(_CONTENT_CHAR.findall(normalized))
    content_ratio = content_chars / max(char_count, 1)
    words = [word.casefold() for word in _WORD.findall(normalized)]
    unique_ratio = len(set(words)) / max(len(words), 1)
    hangul_count = len(_HANGUL.findall(normalized))
    hanja_count = len(_HANJA.findall(normalized))
    hanja_ratio = hanja_count / max(hangul_count + hanja_count, 1)

    length_score = min(char_count / 180.0, 1.0)
    density_score = min(content_ratio / 0.55, 1.0)
    vocabulary_score = min(len(words) / 18.0, 1.0) * min(unique_ratio / 0.45, 1.0)
    # 이 프로젝트의 원문은 한국어/영어다. 한글 자리에 한자가 대량으로 나타나는 것은
    # PaddleOCR 언어 모델 또는 PDF ToUnicode 매핑이 깨진 전형적인 신호이므로 강하게 차단한다.
    corruption_penalty = min(hanja_ratio / 0.30, 1.0) * 0.70
    if _REPEATED_PUNCT.search(normalized):
        corruption_penalty += 0.10

    score = max(0.0, min(1.0, 0.45 * length_score + 0.30 * density_score + 0.25 * vocabulary_score - corruption_penalty))
    reasons: list[str] = []
    if char_count < 40:
        reasons.append(f"텍스트가 너무 짧음({char_count}자)")
    if content_ratio < 0.35:
        reasons.append("인식 가능한 문자 비율이 낮음")
    if len(words) < 6:
        reasons.append(f"의미 있는 단어가 적음({len(words)}개)")
    if hanja_ratio > 0.15:
        reasons.append("한글 대비 한자 비율이 높아 폰트/OCR 깨짐 가능성")

    return ExtractionQuality(
        score=round(score, 4),
        char_count=char_count,
        content_char_ratio=round(content_ratio, 4),
        word_count=len(words),
        unique_word_ratio=round(unique_ratio, 4),
        hanja_to_korean_ratio=round(hanja_ratio, 4),
        reasons=reasons,
    )


def choose_better_extraction(primary: str, fallback: str) -> tuple[str, ExtractionQuality, str]:
    """두 OCR 결과를 같은 기준으로 비교해 더 나은 결과와 선택 경로를 반환한다."""
    primary_quality = evaluate_extraction_quality(primary)
    fallback_quality = evaluate_extraction_quality(fallback)
    if fallback_quality.score > primary_quality.score:
        return fallback, fallback_quality, "fallback"
    return primary, primary_quality, "primary"
