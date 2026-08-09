# RAG 프로젝트 시험용 데이터 모음

| 폴더 | 용도 | 상태 |
|---|---|---|
| `01_korean_rag_allganize/` | 한국어 RAG 전체 파이프라인 검증 (문단/표/이미지 근거 질문 포함) | 다운로드 스크립트만 포함 (huggingface.co 차단으로 직접 다운로드 불가) |
| `02_table_recognition/` | 표 추출 모듈(`table_extraction`) 정확도 검증 | 링크/절차 안내만 포함 (외부 클라우드 호스팅으로 직접 다운로드 불가) |
| `03_cross_lingual_xquad/` | 교차언어(다국어 문서 해석) 시나리오 검증 | **실제 데이터 다운로드 완료** (github 호스팅이라 이 환경에서 바로 받았습니다) |

## 왜 일부는 실제 파일이고 일부는 스크립트만 있나요

이 작업 환경은 네트워크 접근이 화이트리스트 방식으로 제한되어 있어 (github.com, pypi.org 등만 허용),
huggingface.co나 각 기관의 자체 클라우드 스토리지에는 접근할 수 없습니다.
github에 데이터가 직접 올라가 있는 XQuAD만 실제로 받아서 포함했고, 나머지는 다운로드 스크립트와
정확한 절차를 안내해드렸으니 본인 환경(폐쇄망 반입 전 인터넷 접속 가능한 PC)에서 그대로 실행하시면 됩니다.

## 권장 시험 순서

1. `01_korean_rag_allganize` 다운로드 후 전체 파이프라인(청킹→임베딩→검색→리랭킹→답변) 1차 검증
2. `02_table_recognition`의 PubTabNet 샘플로 `table_extraction` 모듈만 별도 정확도 측정
3. `03_cross_lingual_xquad`로 Qwen2.5 + bge-m3 조합의 교차언어 대응력 검증
