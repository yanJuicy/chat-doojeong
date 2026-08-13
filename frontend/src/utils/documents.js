import { PROCESSING_STATUSES, STATUS_LABELS } from "../constants/documents";

export function documentStatusClass(status) {
  if (status === "ready") return "ready";
  if (PROCESSING_STATUSES.has(status)) return "processing";
  return "attention";
}

export function documentProgress(document) {
  const current = Number(document.current_page);
  const total = Number(document.total_pages);
  const hasPages =
    document.status === "extracting" &&
    Number.isFinite(current) &&
    Number.isFinite(total) &&
    total > 0;

  if (hasPages) {
    const percent = Math.max(0, Math.min(100, Math.round((current / total) * 100)));
    return {
      label: `원문 추출 중 · ${current}/${total}페이지 · ${percent}%`,
      percent,
    };
  }

  const labels = {
    uploaded: "처리 순서를 기다리고 있습니다.",
    extracting: "원문 추출을 준비하고 있습니다.",
    extracted: "원문 추출 완료 · 청킹 대기",
    chunked: "청킹 완료 · 임베딩 처리 중",
    embedding: "임베딩 처리 중",
    ready: "검색 가능한 문서입니다.",
    failed: "처리에 실패했습니다.",
    needs_review: "추출 결과 확인이 필요합니다.",
  };
  return { label: labels[document.status] ?? STATUS_LABELS[document.status] ?? document.status, percent: null };
}

export function canDeleteDocument(document) {
  return !["extracting", "extracted", "chunked", "embedding"].includes(document.status);
}

export function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
