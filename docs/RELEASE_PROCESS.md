# 원본·릴리스 관리 원칙

## 유일한 원본

이 PC에서는 아래 Git 저장소의 `master` 브랜치만 편집한다.

```text
C:\Users\mesul\Desktop\rag_chatbot_project_TRUE_LATEST\rag_chatbot_project
```

과거 ZIP과 중간 개선 폴더는 참고자료일 뿐 원본이 아니다. 릴리스 ZIP을 압축 해제해 수정한 뒤 다시
원본으로 삼지 않는다.

## 산출물 구분

- 코드: `git archive`로 태그된 커밋에서 생성
- 데이터: `scripts/backup.ps1`의 시점 백업
- 모델: 별도 대용량 모델 묶음
- 오프라인 설치: 별도 `wheelhouse`와 Docker image tar

## 최종 승인 조건

1. Git 작업 트리가 깨끗함
2. 전체 단위 테스트 통과
3. PowerShell 5.1 파서 오류 0
4. `docker compose config` 통과
5. `/health`의 모든 항목 `ok`
6. 백업 SHA256 dry-run 통과
7. 격리 PostgreSQL/Qdrant 복원 수량 일치
8. 태그·코드 ZIP·SHA256 기록
