# 스택 결정 사항 (DECISIONS.md)

지금까지 논의를 통해 확정된 구성요소와 그 이유를 정리합니다. 구현 중 흔들리지 않도록 기준점으로 삼으세요.

| 구성요소 | 선택 | 이유 |
|---|---|---|
| 웹 프레임워크 | FastAPI | 비동기 처리, Pydantic 통합 |
| LLM | Qwen2.5 (Ollama 서빙) | 외국 문서 해석/교차언어 답변 필요 → 다국어 성능이 EXAONE보다 넓음. 온프레미스 로컬 서빙 |
| 임베딩 | BAAI/bge-m3 | 다국어(한국어+외국어) 성능 최상위권, dense+sparse 동시 지원으로 하이브리드 검색 가능 |
| 벡터DB | Qdrant | 자체 호스팅, 메타데이터 필터링 강력, bge-m3 하이브리드 검색 지원, 폐쇄망 배포 용이 |
| 리랭킹 | BAAI/bge-reranker-v2-m3 | Cross-encoder 기반 정확도, 다국어 지원, 로컬 서빙 가능 |
| RDB | PostgreSQL | 메타데이터/대화이력 저장, 필요시 pgvector로 벡터 통합도 가능 |
| OCR | PaddleOCR (PP-StructureV2/SLANet) | 표 구조 인식 포함, 완전 로컬 |
| 표 인식 폴백 | Qwen2-VL (Ollama) | PaddleOCR confidence 낮은 표만 재추출 |
| 청킹 | 의미기반(Semantic) 청킹 | 정확도 우선 조건에서 고정길이/재귀분할보다 문맥 경계 보존 우수 |
| 형태소분석/키워드 | kiwipiepy | 순수 Python, 폐쇄망 설치 용이 |

## 공통 코딩 규칙

- 모든 함수 타입 힌트 필수
- Pydantic 모델 적극 사용
- 환경변수는 `.env`로 관리 (Pydantic Settings)
- `print()` 대신 `logging` 사용
- 주석은 한국어
- 외부 서비스(LLM, 임베딩, 벡터DB, 리랭커)는 반드시 인터페이스(ABC)로 추상화하여 구현체 교체 가능하도록 유지
- 보안 요건: 완전 폐쇄망(air-gapped) 전제 — 모든 모델은 가중치를 사전 다운로드해 로컬 경로에서 로딩

## 진행 상황

- [x] 표 추출 모듈(`app/services/table_extraction/`) 구현 완료
- [ ] 임베딩/청킹 모듈
- [ ] 벡터DB 연동
- [ ] 리랭킹 모듈
- [ ] LLM Provider 연동
- [ ] DB 모델/세션
- [ ] FastAPI 라우터

## 참고 (이전 세션에서 진행됐던 내용 — 코드 자체는 유실됨)

이전에 별도 세션에서 아래 단계까지 코드를 작성한 이력이 있습니다. 이번에 새로 시작하시더라도
설계 방향 참고용으로 남겨둡니다 (실제 파일은 세션 초기화로 남아있지 않음):
- 1단계: 최소 챗봇 서버 (FastAPI + Ollama + POST /api/chat)
- 2단계: 문서 업로드/PDF·텍스트 추출/청킹/임베딩/Qdrant 저장/내부검색
- 3단계: LLM 기반 질문 분석 구조화 + 규칙기반 폴백 + 민감정보 마스킹
