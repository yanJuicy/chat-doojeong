"""여러 곳(의도 분류, 질문 캐싱)에서 공용으로 쓰는 유사도 유틸."""
from __future__ import annotations

import numpy as np


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """두 벡터 사이의 코사인 유사도를 계산한다 (-1.0 ~ 1.0)."""
    vec_a, vec_b = np.array(a), np.array(b)
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    if denom == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / denom)
