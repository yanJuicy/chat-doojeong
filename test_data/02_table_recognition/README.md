# 표 인식(Table Recognition) 테스트 데이터셋

이 데이터셋들도 huggingface.co / 별도 클라우드 스토리지(IBM Cloud, Microsoft 등)에 호스팅되어 있어
현재 작업 환경(폐쇄망 시뮬레이션)에서는 직접 다운로드가 차단됩니다. 접근 가능한 환경에서 아래 절차로 받으세요.

## 1. PubTabNet (추천 — 시작하기 가장 쉬움)

- 저장소: https://github.com/ibm-aur-nlp/PubTabNet
- 표 이미지 + HTML 구조 라벨이 포함되어 있어, `table_extraction` 모듈의 `to_markdown()` 출력과
  직접 비교(TEDS 지표 등)하기 좋습니다.
- 저장소 README의 다운로드 링크(IBM Cloud Object Storage)를 따라 받으세요.

## 2. PubTables-1M (대규모, 정밀 검증용)

- 저장소: https://github.com/microsoft/table-transformer
- 947,642개의 완전 주석 표, 셀 단위 bounding box까지 포함되어 병합 셀(rowspan/colspan) 검증에 특히 유용합니다.
- 저장소 내 다운로드 안내(Microsoft Research Open Data) 참고.

## 3. ICDAR-2013 표 데이터셋 (소규모, 빠른 벤치마킹용)

- 검색: "ICDAR 2013 table competition dataset"
- 256개 표, 다양한 문서 도메인에서 전문가가 직접 라벨링한 소규모 고품질 데이터셋.
- 규모가 작아 `table_extraction` 파이프라인의 빠른 회귀 테스트(regression test)용으로 적합합니다.

## 테스트 방법 제안

1. PubTabNet 샘플 100~200장으로 먼저 `PaddleTableEngine` 단독 정확도 확인
2. confidence < threshold로 분류된 표만 골라 `VLMTableEngine` 폴백 결과와 비교
3. TEDS(Tree-Edit-Distance-based Similarity) 지표로 HTML 구조 정확도 정량 측정
   (참고 구현: https://github.com/ibm-aur-nlp/PubTabNet 저장소 내 `src/metric.py`)
