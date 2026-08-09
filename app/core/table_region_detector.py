"""
페이지 이미지에 표(격자선)가 있어 보이는지, 무거운 OCR 모델 없이 빠르게 판별한다.

표는 보통 길게 이어진 가로선/세로선으로 구성된다. 이 특징을 모폴로지 연산(morphological
operation)으로 잡아내면, 딥러닝 모델 없이도 수 밀리초 안에 "표가 있을 것 같은지"를 꽤
정확하게 판단할 수 있다. 이걸로 페이지마다 무거운 PPStructureV3(표 구조 인식 포함)를 쓸지,
가벼운 텍스트 전용 OCR을 쓸지 미리 걸러낸다 — 대부분의 일반 텍스트 페이지는 표가 없으므로
가벼운 경로로 보내서 전체 처리 시간을 크게 줄인다.
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def page_likely_has_table(image: Image.Image, min_line_fraction: float = 0.3) -> bool:
    """
    이미지 안에 표로 볼 만한 긴 가로선+세로선이 둘 다 있는지 판단한다.

    Args:
        image: 판별할 페이지 이미지
        min_line_fraction: 선으로 인정할 최소 길이 (이미지 가로/세로 길이 대비 비율).
                            너무 낮으면 글자 밑줄 같은 것도 선으로 오인하고, 너무 높으면
                            실제 표의 짧은 구분선을 놓친다.

    Returns:
        표가 있을 것으로 보이면 True (그러면 무거운 PPStructureV3로 보냄)
    """
    import cv2

    gray = np.array(image.convert("L"))
    height, width = gray.shape

    # 이진화(흑백 반전): 어두운 선/글자가 흰색(255)이 되게 해서 모폴로지 연산이 잘 걸리게 한다.
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10
    )

    # 가로선만 남기는 커널(가로로 길고 세로로 얇음)로 열기 연산 -> 글자는 지워지고 긴 가로선만 남음
    horizontal_kernel_len = max(int(width * min_line_fraction), 10)
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_kernel_len, 1))
    horizontal_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)

    # 세로선만 남기는 커널
    vertical_kernel_len = max(int(height * min_line_fraction), 10)
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_kernel_len))
    vertical_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)

    has_horizontal = bool(np.any(horizontal_lines > 0))
    has_vertical = bool(np.any(vertical_lines > 0))

    # 표는 보통 가로선+세로선이 격자를 이루므로, 둘 다 있어야 표로 판단한다.
    # (가로선만 있으면 밑줄/구분선일 뿐일 수 있고, 세로선만 있으면 여백/장식일 수 있다.)
    return has_horizontal and has_vertical
