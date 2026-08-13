import {
  CONVERSATION_STORAGE_KEY,
  DEFAULT_CONVERSATION_TITLE,
  DEFAULT_MESSAGE,
  MAX_CONVERSATION_TITLE_LENGTH,
} from "../constants/chat";

function createId(prefix) {
  const randomId = globalThis.crypto?.randomUUID?.();
  return randomId ? `${prefix}-${randomId}` : `${prefix}-${Date.now()}-${Math.random()}`;
}

function freshWelcomeMessage() {
  return { ...DEFAULT_MESSAGE };
}

export function createConversation(title = DEFAULT_CONVERSATION_TITLE) {
  const now = new Date().toISOString();
  return {
    id: createId("conversation"),
    title,
    isTitleCustom: title !== DEFAULT_CONVERSATION_TITLE,
    messages: [freshWelcomeMessage()],
    createdAt: now,
    updatedAt: now,
  };
}

export function titleFromQuestion(question) {
  const compact = question.replace(/\s+/g, " ").trim();
  if (compact.length <= 28) return compact;
  return `${compact.slice(0, 28).trim()}…`;
}

export function latestSourceMessageId(messages) {
  return [...messages].reverse().find((message) => message.sources?.length)?.id ?? null;
}

function normalizeConversation(conversation) {
  if (!conversation || typeof conversation !== "object" || !conversation.id) return null;
  const storedMessages = Array.isArray(conversation.messages) ? conversation.messages : [];
  const messages = storedMessages.length
    ? storedMessages.map((message) =>
        message?.pending
          ? {
              ...message,
              pending: false,
              progress: "",
              content: message.content || "새로고침으로 답변 생성이 중단되었습니다.",
            }
          : message,
      )
    : [freshWelcomeMessage()];
  const title = String(conversation.title || DEFAULT_CONVERSATION_TITLE)
    .trim()
    .slice(0, MAX_CONVERSATION_TITLE_LENGTH) || DEFAULT_CONVERSATION_TITLE;

  return {
    id: String(conversation.id),
    title,
    isTitleCustom: Boolean(conversation.isTitleCustom),
    messages,
    createdAt: conversation.createdAt || new Date().toISOString(),
    updatedAt: conversation.updatedAt || conversation.createdAt || new Date().toISOString(),
  };
}

export function loadConversationState() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONVERSATION_STORAGE_KEY));
    const conversations = Array.isArray(saved?.conversations)
      ? saved.conversations.map(normalizeConversation).filter(Boolean)
      : [];
    if (conversations.length) {
      const activeConversationId = conversations.some(
        (conversation) => conversation.id === saved.activeConversationId,
      )
        ? saved.activeConversationId
        : conversations[0].id;
      return { conversations, activeConversationId };
    }
  } catch {
    // 손상되었거나 사용할 수 없는 브라우저 저장소는 새 대화로 복구한다.
  }

  const conversation = createConversation();
  return { conversations: [conversation], activeConversationId: conversation.id };
}

export function saveConversationState(state) {
  try {
    localStorage.setItem(CONVERSATION_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // 저장 공간 부족이나 비공개 모드에서도 현재 화면의 채팅은 계속 사용할 수 있다.
  }
}
