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

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
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
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)  # raw_text의 SHA256, 자동 중복 감지용
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
    parent_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # Parent-Child 청킹: 이 청크(자식)가 속한 더 큰 맥락(부모). 검색은 text로, 답변 생성 시 맥락은 이걸로.

    document: Mapped["Document"] = relationship(back_populates="chunks")


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_language: Mapped[str | None] = mapped_column(String, nullable=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatSession(Base):
    """
    멀티턴 대화 세션 하나. FE가 새 대화를 시작할 때 UUID를 만들어 이 id로 쓴다.
    이 프로젝트엔 로그인이 없어서 "누구의 세션인지"는 구분하지 않는다 — 이 id를
    아는 클라이언트가 그 대화의 주인이라고 취급한다(사내 폐쇄망이라 감수하는 리스크).
    """

    __tablename__ = "chat_sessions"

    # FE(crypto.randomUUID() 기반)가 만든 값을 그대로 PK로 쓴다. 서버가 별도로 발급하지
    # 않고, 처음 보는 id로 메시지가 들어오면 그 자리에서 새로 생성한다(get-or-create).
    id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # 새 turn이 저장될 때마다 갱신된다. 지금은 안 쓰지만, 나중에 "최근 대화 목록"을
    # 만들 때 정렬 기준으로 쓸 수 있어서 미리 남겨둔다.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    turns: Mapped[list["ChatTurn"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatTurn(Base):
    """
    ChatSession 안의 발화 하나 (사용자 질문 1개 또는 챗봇 답변 1개 = 각각 별도 행).
    멀티턴 질문 재작성(이전 대화를 보고 "그럼 무게는?"을 "RB-Y1의 무게는?"으로
    바꾸는 것)의 재료가 되는 이력이 여기 쌓인다.
    """

    __tablename__ = "chat_turns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)

    # "user" 또는 "assistant" — 재작성 프롬프트를 만들 때 누가 한 말인지 구분해야 해서 필요.
    role: Mapped[str] = mapped_column(String)

    # role=user면 사용자가 실제로 입력한 원문 그대로("그럼 무게는?").
    # role=assistant면 최종 답변 전문.
    content: Mapped[str] = mapped_column(Text)

    # role=user인 행에만 채워진다 — 질문 재작성이 실제로 검색에 넘긴 standalone 질문
    # ("RB-Y1의 무게는?"). 재작성이 안 일어났으면(첫 질문/이미 완결된 질문/재작성 실패)
    # None으로 남겨서, 나중에 "왜 이런 검색 결과가 나왔는지" 원인 추적에 쓴다.
    rewritten_question: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["ChatSession"] = relationship(back_populates="turns")


class WorkReportEntry(Base):
    """
    주간(추후 월간도 가능) 업무보고 원자료 항목 하나. 채팅으로 직접 입력하거나 기존
    보고서 문서(표)를 업로드해서 추출한 뒤, 정제(문체 정규화)를 거쳐 여기 저장된다.

    "구분"(사업/관리/시군특화... 등 원본 문서마다 다를 수 있는 값)은 고정 enum으로
    만들지 않는다. 최종 보고서를 뽑을 타겟 양식의 구분 체계가 원본과 다를 수 있어서
    (예: 원본은 구분 3개, 타겟 양식은 구분 1개), 저장 시점엔 source_category에 원본
    표기를 느슨한 태그로만 보존하고, 실제로 어느 칸에 넣을지는 보고서 생성 시점에
    타겟 양식을 보고 결정한다 (다대일 병합은 정보 손실 없이 가능, 반대로 저장 시점에
    미리 못 박아두면 나중에 다른 구분 체계의 양식이 필요할 때 재분류가 필요해짐).
    """

    __tablename__ = "work_report_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    department: Mapped[str] = mapped_column(String)

    # "실적" 또는 "계획"
    entry_type: Mapped[str] = mapped_column(String)

    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)

    # 원본 문서/채팅에서 온 구분 표기 (예: "사업", "관리", "시군특화일자리사업단"). 느슨한
    # 태그일 뿐 스키마로 강제하지 않는다 — 위 클래스 docstring 참고.
    source_category: Mapped[str | None] = mapped_column(String, nullable=True)

    # 정제 파이프라인을 거쳐 격식체 짧은 문장("~완료/~실시" 등)으로 다듬어진 최종 문장.
    content: Mapped[str] = mapped_column(Text)

    # "chat" 또는 "document"
    source: Mapped[str] = mapped_column(String)

    # source=document일 때만 채워짐. 문서가 삭제돼도 과거에 뽑아둔 보고 항목은 남아있어야
    # 하므로(이미 확정 제출된 보고서의 근거 자료), FK 제약을 걸지 않고 참조 정보로만 둔다.
    source_document_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # source=chat일 때 사용자가 실제로 입력한 원문. 정제 결과(content)가 의심스러울 때
    # 원문과 대조해서 검증/수정할 수 있게 남겨둔다.
    raw_input: Mapped[str | None] = mapped_column(Text, nullable=True)

    # source=document일 때만 채워짐. 원본 표 셀에서 이 항목이 어떤 표현 형식으로 쓰여
    # 있었는지(report_table_parser가 정규식으로 감지) — "bullet:•", "bullet:-"처럼 글머리
    # 기호를 썼으면 그 기호를, 기호 없이 문장 하나로 쓰여 있었으면 "prose"를 저장한다.
    # 최종 보고서 DOCX를 만들 때 이 부서의 원본 문서가 쓰던 표현 형식을 그대로 재현하는 데 쓴다
    # (weekly_report_composer.detect_department_format 참고).
    source_format: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkReportDocument(Base):
    """
    주간보고서 작성용으로 업로드된 원본 PDF 파일 1개. work_report_entries.source_document_id가
    가리키는 대상 — 파일은 처음부터 디스크에 저장돼 있었지만(work_reports.py의 upload_document),
    그 경로를 조회/재다운로드할 DB 행이 없어서 추가했다. 일반 문서(documents 테이블)와는
    별개로 둔다 — 목적이 검색이 아니라 표 데이터 추출이라 OCR/청킹/임베딩 파이프라인을 타지 않는다.
    """

    __tablename__ = "work_report_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    pages_with_table: Mapped[int] = mapped_column(default=0)
    pages_without_table: Mapped[int] = mapped_column(default=0)
    entries_created: Mapped[int] = mapped_column(default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
