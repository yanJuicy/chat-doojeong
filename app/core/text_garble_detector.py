"""
PDF에서 뽑아낸 "디지털 텍스트"가 실제로는 폰트 인코딩 문제로 깨진 글자인지 판별한다.

일부 PDF(특히 디자인 툴에서 만들어진 한국어 문서)는 폰트를 서브셋으로 박아넣으면서
글자 코드와 실제 유니코드 사이의 매핑(ToUnicode CMap)이 비표준이거나 손상돼 있는
경우가 있다. 이러면 PyMuPDF가 "텍스트 레이어가 있다"고 정상 판단해서 OCR을 건너뛰는데,
실제로 뽑히는 텍스트는 전혀 엉뚱한 한자로 치환된 의미 없는 글자다.

판별 원리: 정상적인 한국어 문서는 한글(가-힣) 비중이 압도적으로 높고 일반 한자(정식 한자어)는
드물게만 섞인다. 근데 이 인코딩 깨짐 현상은 한글이 있어야 할 자리에 한자 유니코드 영역의
글자로 치환되는 패턴이라, "한글 대비 한자 비율"이 비정상적으로 높게 나온다.
"""
from __future__ import annotations

# 이 비율을 넘으면(한글+한자 중 한자가 이 비율 이상이면) 깨진 텍스트로 판단한다.
# 정상 한국어 문서는 보통 한자 비율이 몇 % 이내(고유명사 등)이므로 여유 있게 잡음.
_GARBLED_HANJA_RATIO_THRESHOLD = 0.15
# 판별에 쓸 최소 표본 크기 (너무 짧은 텍스트는 우연히 비율이 튈 수 있어 판단을 건너뜀)
_MIN_SAMPLE_CJK_CHARS = 20


def is_text_garbled(text: str) -> bool:
    """이 텍스트가 폰트 인코딩 문제로 깨진 것으로 보이면 True를 반환한다."""
    hangul_count = sum(1 for c in text if 0xAC00 <= ord(c) <= 0xD7A3)
    hanja_count = sum(1 for c in text if 0x4E00 <= ord(c) <= 0x9FFF)
    total = hangul_count + hanja_count

    if total < _MIN_SAMPLE_CJK_CHARS:
        return False  # 표본이 너무 적으면(영어 위주 문서 등) 판단하지 않음

    hanja_ratio = hanja_count / total
    return hanja_ratio >= _GARBLED_HANJA_RATIO_THRESHOLD
