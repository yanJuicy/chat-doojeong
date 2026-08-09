# 실제 검증된 조합(Python 3.11, transformers 4.57.6, paddlepaddle 3.2.2)을 그대로 고정한다.
FROM python:3.11-slim

WORKDIR /app

# opencv/paddleocr가 필요로 하는 시스템 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
COPY app/services/table_extraction/requirements.txt ./table_extraction_requirements.txt

# 네트워크 불안정으로 인한 해시 불일치/다운로드 실패 시 pip가 자체적으로 재시도하도록 설정
ENV PIP_RETRIES=5
ENV PIP_DEFAULT_TIMEOUT=100

# Windows에서 실제로 겪었던 버전 문제를 그대로 반영해서 고정 설치한다.
# 단계를 나눠서, 특정 단계에서 실패해도 Docker 레이어 캐시 덕분에 그 이전 단계는 재다운로드하지 않는다.
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "transformers>=4.56,<5.0"
RUN pip install --no-cache-dir sentencepiece protobuf python-multipart pymupdf
RUN pip install --no-cache-dir -r table_extraction_requirements.txt
RUN pip install --no-cache-dir "paddlex[ocr]"
RUN pip install --no-cache-dir --force-reinstall paddlepaddle==3.2.2

COPY app/ ./app
# DB 스키마는 create_all()이 아니라 Alembic이 관리한다 (기존 테이블 변경 불가 문제 때문).
# 컨테이너로 앱을 띄우는 경로(docker-compose.yml의 --profile container-app)에서도
# 빈 DB에서 곧바로 시작할 수 있도록 마이그레이션 파일을 함께 넣는다.
COPY alembic.ini ./
COPY migrations/ ./migrations

EXPOSE 8000
# 시작 전에 항상 alembic upgrade head를 먼저 실행한다 — 새 컴퓨터의 빈 DB든,
# 컬럼이 추가된 기존 DB든 이 한 줄로 동일하게 최신 스키마를 보장한다.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
