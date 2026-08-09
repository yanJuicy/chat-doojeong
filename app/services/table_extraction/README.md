# 표 추출 모듈

현재 운영 경로는 PDF·이미지 추출기가 `PaddleTableEngine`을 직접 지연 로딩해 사용한다.
표가 감지된 페이지만 PPStructureV3를 실행하고, 나머지는 경량 PaddleOCR 경로를 사용한다.
표 마커와 Markdown 공통 처리는 `app/core/table_markdown.py`에 있다.
