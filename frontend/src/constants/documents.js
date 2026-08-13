export const PROCESSING_STATUSES = new Set([
  "uploaded",
  "extracting",
  "extracted",
  "chunked",
  "embedding",
]);

export const STATUS_LABELS = {
  uploaded: "처리 대기",
  extracting: "원문 추출 중",
  extracted: "청킹 대기",
  chunked: "임베딩 대기",
  embedding: "임베딩 중",
  ready: "검색 가능",
  failed: "처리 실패",
  needs_review: "확인 필요",
};
