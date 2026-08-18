"""
SQLAlchemy 모델 (PostgreSQL, 비동기 asyncpg 드라이버 사용 전제).

설계 원칙 (DB 중심 아키텍처):
  OCR/청킹/임베딩 각 단계는 서로를 함수 호출로 직접 알지 못한다.
  대신 Document.status를 거쳐가며, 각 워커(app/workers/*)가 자기 단계의 상태만 보고
  DB를 읽고 쓴다. 그래서 한 단계(예: OCR 엔진)를 통째로 교체해도
  다른 단계는 코드를 한 줄도 고칠 필요가 없다 — DB 스키마(계약)만 지키면 된다.

  status 흐름: uploaded -> extracted -> chunked -> ready (실패 시 failed)
"""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class DocumentStatus(str, enum.Enum):
    """문서가 파이프라인의 어느 단계까지 처리됐는지를 나타내는 상태.
    각 워커는 자기 담당 상태의 문서만 조회해서 처리하고 다음 상태로 넘긴다."""

    UPLOADED = "uploaded"      # 파일만 저장됨, 아직 텍스트 추출 전 (extraction_worker 대상)
    EXTRACTING = "extracting"  # 추출(OCR 포함) 진행 중 — 이 상태인 동안은 잠금 없이 오래 걸리는 작업을 함
    NEEDS_REVIEW = "needs_review"  # 추출은 끝났지만 OCR 품질이 낮아 사람 확인/재처리가 필요함
    EXTRACTED = "extracted"    # OCR/텍스트 추출 완료, 청킹 전 (chunking_worker 대상)
    CHUNKED = "chunked"        # 청킹 완료, 임베딩 전 (embedding_worker 대상)
    READY = "ready"            # 임베딩까지 완료, 검색 가능한 상태
    FAILED = "failed"          # 어느 단계에서든 실패 (error_message 참고)


class WorkItemStatus(str, enum.Enum):
    """사용자가 관리하는 업무의 현재 상태."""

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)  # 원본 파일 저장 위치 (extraction_worker가 읽는 경로)
    file_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # sha256, 동일 파일 재업로드 감지용
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        default=DocumentStatus.UPLOADED,
        nullable=False,
    )
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # extraction_worker가 채워넣는 결과 (표 마커 포함)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # status=FAILED일 때 원인
    warning_message: Mapped[str | None] = mapped_column(Text, nullable=True)  # 실패는 아니지만 청킹 품질 등에서 감지된 이상 징후
    retry_count: Mapped[int] = mapped_column(default=0)  # 실패 후 자동/수동 재시도된 횟수 (max_retries 넘으면 FAILED로 확정)
    current_page: Mapped[int | None] = mapped_column(nullable=True)  # 추출(OCR) 진행률 - 지금 처리 중인 페이지
    total_pages: Mapped[int | None] = mapped_column(nullable=True)  # 추출(OCR) 진행률 - 전체 페이지 수
    extraction_quality_score: Mapped[float | None] = mapped_column(nullable=True)
    extraction_quality_details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON 진단값
    extraction_method: Mapped[str | None] = mapped_column(String, nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String, nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    chunks: Mapped[list["DocumentChunk"]] = relationship(back_populates="document")
    labels: Mapped[list["DocumentLabel"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class DocumentLabel(Base):
    """
    문서에 붙는 "어디의 무엇" 라벨. documents.source_label(문서당 하나) 대신 별도 테이블로 뺐다 —
    실제로는 문서 하나가 "두정테크"이면서 동시에 "용접방식"이기도 한 것처럼, 회사(누구)와
    주제(뭐에 대한 건지) 등 여러 라벨을 동시에 가지는 경우가 자연스럽다.
    """

    __tablename__ = "document_labels"
    __table_args__ = (UniqueConstraint("document_id", "label", name="uq_document_labels_document_label"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    label: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="labels")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    is_table: Mapped[bool] = mapped_column(default=False)
    table_confidence: Mapped[float | None] = mapped_column(nullable=True)  # 표 청크의 행별 열개수 일관성 비율
    image_path: Mapped[str | None] = mapped_column(String, nullable=True)  # 이미지 캡션 청크인 경우 원본 이미지 경로
    embedded: Mapped[bool] = mapped_column(Boolean, default=False)  # embedding_worker가 처리 완료 시 True로 표시
    embed_retry_count: Mapped[int] = mapped_column(default=0)  # 이 청크의 임베딩이 실패해서 재시도된 횟수

    document: Mapped["Document"] = relationship(back_populates="chunks")


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_language: Mapped[str | None] = mapped_column(String, nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkItem(Base):
    """주간보고서의 근거가 되는 업무의 현재 상태."""

    __tablename__ = "work_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[WorkItemStatus] = mapped_column(
        Enum(WorkItemStatus, values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        default=WorkItemStatus.PLANNED,
        nullable=False,
        index=True,
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    carry_over: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    activities: Mapped[list["WorkActivity"]] = relationship(
        back_populates="work_item",
        cascade="all, delete-orphan",
        order_by="WorkActivity.activity_date, WorkActivity.created_at",
    )


class WorkActivity(Base):
    """특정 날짜에 실제로 수행한 업무 내용."""

    __tablename__ = "work_activities"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    work_item_id: Mapped[str] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[WorkItemStatus | None] = mapped_column(
        Enum(WorkItemStatus, values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    work_item: Mapped["WorkItem"] = relationship(back_populates="activities")


class ReportTemplate(Base):
    """보고서 양식 파일의 버전과 활성 상태를 관리하는 레지스트리."""

    __tablename__ = "report_templates"
    __table_args__ = (UniqueConstraint("report_type", "version", name="uq_report_templates_type_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    field_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GeneratedReport(Base):
    """과거 제출 내용을 재현하기 위한 생성 보고서 스냅샷."""

    __tablename__ = "generated_reports"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    cutoff_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    template_id: Mapped[str | None] = mapped_column(
        ForeignKey("report_templates.id", ondelete="SET NULL"), nullable=True
    )
    content_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
