# Allganize RAG-Evaluation-Dataset-KO

- 소스: https://huggingface.co/datasets/allganize/RAG-Evaluation-Dataset-KO
- 구성: 금융/공공/의료/법률/커머스 5개 도메인 PDF 문서 + 도메인별 60개 질문-정답 쌍 (문단/표/이미지 근거 구분)

## 다운로드 방법

이 작업 환경은 폐쇄망 조건을 시험하기 위해 huggingface.co 접근이 막혀 있어, 대신 다운로드해드릴 수 없습니다.
본인 PC(또는 huggingface.co 접근이 가능한 서버)에서 아래를 실행하세요.

```bash
pip install huggingface_hub
python download.py
```

다운로드 후 폴더 구조는 대략 다음과 같습니다 (원본 저장소 기준):

```
allganize_rag_ko_data/
├── documents/            # 도메인별 PDF 원본
│   ├── finance/
│   ├── public/
│   ├── medical/
│   ├── law/
│   └── commerce/
├── documents.csv          # 문서명, 페이지 수, 링크 목록
└── questions.csv (또는 각 도메인별 파일)  # 질문, 정답, context_type(문단/표/이미지)
```

## 이후 테스트 절차 (참고)

1. `documents/` 안의 PDF를 지금 만든 `table_extraction` 모듈 + 기존 청킹/임베딩 파이프라인에 통과시켜 Qdrant에 적재
2. `questions.csv`의 질문을 챗봇 서버 `/api/chat`에 순서대로 질의
3. 반환된 답변을 정답과 비교 (context_type이 'table'인 질문들만 따로 모아서 표 추출 모듈 정확도를 별도로 확인하면 유용)
