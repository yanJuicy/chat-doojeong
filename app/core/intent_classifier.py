"""
소프트 의도(카테고리) 분류기.

설계 원칙: 검색을 "배제"하는 데 쓰지 않는다. 카테고리 판단이 틀려도 정답이
후보에서 사라지지 않도록, 항상 순위에 작은 가산점만 주는 용도로 쓴다
(하드 필터링은 오분류의 피해가 치명적이라 지양 — 이전 논의에서 정리된 원칙).

카테고리 설명문을 서버 시작 시 한 번만 임베딩해서 재사용한다.
"""
from __future__ import annotations

import numpy as np

from .embeddings import BaseEmbeddingProvider

# 카테고리 설명문 — 실제 문서에서 자주 쓰는 용어를 넣을수록 분류 정확도가 올라간다.
# 협동로봇/사족보행로봇/양팔로봇/서빙로봇/컨트롤박스 제품 문서 도메인에 맞춘 11개 의도.
INTENT_DESCRIPTIONS: dict[str, str] = {
    "overview": (
        "제품 소개, 제품 개요, 로봇이 무엇인지, 제품 목적과 구성, "
        "시스템 구성, 제품 종류와 라인업, RB 시리즈, RBQ, RB-Y1, "
        "서빙로봇의 기본 설명"
    ),
    "feature": (
        "제품의 주요 기능, 특징, 특장점, 장점, 강점, 차별점, "
        "핵심 기술, 자체 개발 부품, 편의 기능, 소프트웨어 기능, "
        "어떤 기능을 지원하는지와 무엇이 가능한지에 관한 내용"
    ),
    "specification": (
        "제품 사양, 스펙, 가반하중, 적재량, 도달거리, 작업반경, "
        "반복정밀도, 무게, 크기, 치수, 축과 관절, 속도, 전력, "
        "전압, 소음, IP 등급, 사용 온도, 포트, I/O와 케이블 구성"
    ),
    "comparison_selection": (
        "로봇 모델 비교, 제품 간 차이점, 제품 선정, 조건에 맞는 모델 추천, "
        "가반하중, 도달거리, 작업반경, 설치 공간, 산업과 공정 요구사항에 "
        "따라 적합한 모델을 찾는 내용"
    ),
    "installation_setup": (
        "설치 방법, 로봇 고정, 조립, 배선, 케이블 연결, 컨트롤박스 연결, "
        "전원 연결, 공압 연결, 툴과 그리퍼 장착, 초기 설정, IP와 네트워크 설정, "
        "설치 절차와 설치 시 주의사항"
    ),
    "operation_programming": (
        "로봇 사용법, 조작법, 운용 절차, 티칭, 직접교시, 프로그램 작성, "
        "동작 명령과 명령어 사용법, 좌표계, 속도와 가속도 설정, "
        "자동 모드, 수동 모드, Make, Play와 Set-up 화면 사용법"
    ),
    "integration_communication": (
        "외부 장비 연동, PLC, 그리퍼, 툴 제어, 디지털 및 아날로그 I/O, "
        "Modbus TCP와 RTU, 소켓, 시리얼, LAN, USB, 포트, 레지스터, "
        "서버와 클라이언트 통신 설정 및 데이터 송수신"
    ),
    "safety_troubleshooting": (
        "안전 기능, 위험, 주의와 경고, 비상정지, 충돌 감지, 자가 충돌, "
        "보호정지, 오류와 에러, 문제 원인, 로봇이 움직이지 않거나 연결되지 않는 "
        "상황의 점검 및 복구 방법"
    ),
    "maintenance_support": (
        "정기 점검, 정비, 유지보수, 수리, 부품 교체, 소모품과 교체 주기, "
        "소프트웨어 및 펌웨어 업데이트, 보증, 서비스 지원, 고장 접수와 문의"
    ),
    "application_solution": (
        "로봇 활용 분야, 적용 사례와 자동화 솔루션, 용접, 조립, 픽앤플레이스, "
        "이송, 머신텐딩, 팔레타이징, 물류, 포장, 식품, 서비스, 연구, 교육, "
        "순찰과 검사 공정에 어떤 제품을 사용할 수 있는지에 관한 내용"
    ),
    "certification_asset": (
        "인증서, 안전 규격과 국제 표준, CE, EMC, MD, KCs, NRTL, CSA, "
        "NSF, TÜV, ISO 인증, 2D 치수 도면, DWG와 CAD 파일, "
        "3D STEP 및 STP 모델, 기술 자료와 파일 다운로드"
    ),
}

# 이 키워드들이 제목처럼(짧은 독립 행, 번호 제목 등) 등장하면 청킹 경계 후보로 쓸 수 있다.
# structured_chunker.py의 제목 감지 로직이 이 목록도 함께 참고한다.
INTENT_SECTION_KEYWORDS: dict[str, list[str]] = {
    "overview": ["제품 소개", "개요", "시스템 구성", "제품 구성", "라인업", "각 부분의 명칭"],
    "feature": ["주요 기능", "특징", "특장점", "장점", "핵심 기술", "차별점"],
    "specification": ["사양", "제품 사양", "Specification", "치수", "제원", "성능"],
    "comparison_selection": ["모델 비교", "제품 비교", "선정 가이드", "라인업 비교"],
    "installation_setup": ["설치", "설치 방법", "연결", "배선", "초기 설정", "네트워크 설정", "장착"],
    "operation_programming": ["사용 방법", "사용법", "조작", "운용", "티칭", "프로그램", "명령어", "동작 모드"],
    "integration_communication": ["통신", "외부 연동", "I/O", "Modbus", "소켓", "시리얼 통신", "레지스터"],
    "safety_troubleshooting": ["안전", "주의", "경고", "오류", "에러", "문제 해결", "복구", "충돌", "비상정지"],
    "maintenance_support": ["점검", "정비", "유지보수", "수리", "부품 교체", "서비스", "업데이트"],
    "application_solution": ["적용 분야", "활용 분야", "적용 사례", "응용", "자동화 솔루션", "도입 절차"],
    "certification_asset": ["인증", "인증서", "규격", "표준", "도면", "2D", "3D", "CAD"],
}


class IntentClassifier:
    """질문/문서 텍스트와 카테고리 설명문 사이의 코사인 유사도를 계산하는 분류기"""

    def __init__(self, embedding_provider: BaseEmbeddingProvider) -> None:
        self._embedding_provider = embedding_provider
        self._category_vectors: dict[str, np.ndarray] | None = None

    async def _ensure_loaded(self) -> None:
        if self._category_vectors is not None:
            return
        names = list(INTENT_DESCRIPTIONS.keys())
        descriptions = list(INTENT_DESCRIPTIONS.values())
        vectors = await self._embedding_provider.embed_documents(descriptions)
        self._category_vectors = {name: np.array(vec) for name, vec in zip(names, vectors)}

    async def classify(self, text: str, precomputed_dense_vector: list[float] | None = None) -> list[dict]:
        """
        텍스트와 각 카테고리 사이의 코사인 유사도를 계산해서, 유사도 내림차순으로 반환한다.
        결론(1등 카테고리)만 주지 않고 전체 카테고리의 점수를 다 보여줘서, 판단 근거를 항상 확인할 수 있게 한다.

        precomputed_dense_vector가 주어지면 그걸 그대로 쓰고, 다시 임베딩하지 않는다.
        (질문 처리 파이프라인은 이미 질문을 한 번 임베딩해뒀으므로, 여기서 또 임베딩하면 중복 호출이 된다 —
        실제로 이 중복이 있었던 걸 지적받아서 고친 부분이다.)
        """
        await self._ensure_loaded()
        assert self._category_vectors is not None

        if precomputed_dense_vector is not None:
            query_vec = np.array(precomputed_dense_vector)
        else:
            query_vec = np.array(await self._embedding_provider.embed_query(text))
        query_norm = np.linalg.norm(query_vec)

        results = []
        for name, cat_vec in self._category_vectors.items():
            cat_norm = np.linalg.norm(cat_vec)
            similarity = float(np.dot(query_vec, cat_vec) / (query_norm * cat_norm + 1e-9))
            results.append({"category": name, "similarity": round(similarity, 4)})

        results.sort(key=lambda r: r["similarity"], reverse=True)
        return results
