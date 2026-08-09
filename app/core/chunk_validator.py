"""
청킹이 "정확하게" 됐는지 자동으로 점검하는 검증기.

완벽한 정답을 판단할 수는 없지만, 아래 신호들은 실제로 청킹이 잘못됐을 때 흔히 나타나는
패턴이라 이걸로 이상 징후가 있는 문서를 자동으로 걸러내서 재검토 대상으로 표시할 수 있다.
"""
from __future__ import annotations

import re

from .chunking import Chunk

_TABLE_START_MARKER = "<!-- TABLE_BLOCK_START -->"
_TABLE_END_MARKER = "<!-- TABLE_BLOCK_END -->"
_IMAGE_BLOCK_PATTERN = re.compile(r'<!-- IMAGE_BLOCK_START path="[^"]+" -->.*?<!-- IMAGE_BLOCK_END -->', re.DOTALL)

_MIN_REASONABLE_CHUNK_LENGTH = 10     # 이보다 짧은 청크는 의미 있는 내용이 거의 없을 가능성이 높음
_MAX_REASONABLE_CHUNK_LENGTH = 4000   # 이보다 길면 max_tokens 설정이 무시됐거나 분할이 안 된 것
_MIN_ACCEPTABLE_COVERAGE_RATIO = 0.85  # 원문(표 제외) 대비 청크 합산 글자수가 이 비율 밑이면 유실 의심


def validate_chunks(original_text: str, chunks: list[Chunk]) -> list[str]:
    """
    청킹 결과를 검증해서 경고 메시지 목록을 반환한다 (비어있으면 이상 없음).
    이 함수는 파이프라인을 막지 않는다 — 호출자가 경고를 기록만 하고 계속 진행하는 용도.
    """
    warnings: list[str] = []

    if not chunks:
        warnings.append("청크가 하나도 생성되지 않았습니다 (원문이 비었거나 청킹 로직 오류 가능성).")
        return warnings

    # 1) 표 마커 짝이 맞는지 (원문 자체의 무결성 확인 — OCR/추출 단계 문제도 여기서 잡힘)
    n_start = original_text.count(_TABLE_START_MARKER)
    n_end = original_text.count(_TABLE_END_MARKER)
    if n_start != n_end:
        warnings.append(f"표 마커 짝이 안 맞습니다 (시작 {n_start}개 vs 종료 {n_end}개) — 추출 단계에서 표가 깨졌을 수 있습니다.")

    # 2) 원문(표+이미지 블록 제외) 대비 청크 합산 글자수 커버리지 확인
    #    이미지 블록은 원문에 마커+경로+캡션 전체가 들어있지만, 청크의 text는 캡션만 담고 있어서
    #    제외하지 않으면 실제로 유실이 없어도 "유실 의심"으로 잘못 판정된다.
    non_special_original = re.sub(
        rf"{re.escape(_TABLE_START_MARKER)}.*?{re.escape(_TABLE_END_MARKER)}", "", original_text, flags=re.DOTALL
    )
    non_special_original = _IMAGE_BLOCK_PATTERN.sub("", non_special_original)
    non_special_original_len = len(non_special_original.strip())

    plain_text_chunks = [c for c in chunks if not c.is_table and not c.image_path]
    plain_text_chunk_len = sum(len(c.text) for c in plain_text_chunks)

    if non_special_original_len > 0:
        coverage_ratio = plain_text_chunk_len / non_special_original_len
        if coverage_ratio < _MIN_ACCEPTABLE_COVERAGE_RATIO:
            warnings.append(
                f"원문 대비 청크 커버리지가 낮습니다 ({coverage_ratio:.0%}) — 청킹 과정에서 내용이 유실됐을 수 있습니다."
            )

    # 3) 비정상적으로 짧거나 긴 청크 비율 확인 (표/이미지 캡션 청크는 원래 짧을 수 있어 제외)
    if plain_text_chunks:
        too_short = sum(1 for c in plain_text_chunks if len(c.text) < _MIN_REASONABLE_CHUNK_LENGTH)
        too_long = sum(1 for c in plain_text_chunks if len(c.text) > _MAX_REASONABLE_CHUNK_LENGTH)

        if too_short / len(plain_text_chunks) > 0.2:
            warnings.append(f"너무 짧은 청크가 많습니다 ({too_short}/{len(plain_text_chunks)}개) — 문장 분리가 과도하게 잘게 됐을 수 있습니다.")
        if too_long > 0:
            warnings.append(f"너무 긴 청크가 있습니다 ({too_long}개) — max_tokens 설정이 제대로 적용 안 됐을 수 있습니다.")

    return warnings
