export const DEFAULT_MESSAGE = {
  id: "welcome",
  role: "assistant",
  content:
    "등록된 사내 문서를 근거로 답변합니다. 제품 사양, 설치 절차, 안전 기준처럼 문서에서 확인할 내용을 질문해 주세요.",
  sources: [],
};

export const DEFAULT_CONVERSATION_TITLE = "새 대화";
export const CONVERSATION_STORAGE_KEY = "document-intelligence-conversations-v1";
export const MAX_CONVERSATION_TITLE_LENGTH = 60;
