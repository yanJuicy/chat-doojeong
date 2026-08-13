import { useEffect, useMemo, useRef, useState } from "react";
import { streamQuestion } from "../api";
import { DEFAULT_CONVERSATION_TITLE, MAX_CONVERSATION_TITLE_LENGTH } from "../constants/chat";
import {
  createConversation,
  latestSourceMessageId,
  loadConversationState,
  saveConversationState,
  titleFromQuestion,
} from "../utils/conversations";

export default function useChat() {
  const [conversationState, setConversationState] = useState(loadConversationState);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [sourceMessageId, setSourceMessageId] = useState(() => {
    const active = conversationState.conversations.find(
      (conversation) => conversation.id === conversationState.activeConversationId,
    );
    return latestSourceMessageId(active?.messages ?? []);
  });
  const [selectedSourceId, setSelectedSourceId] = useState(null);
  const [mobileSourcesOpen, setMobileSourcesOpen] = useState(false);
  const abortRef = useRef(null);
  const activeConversationIdRef = useRef(conversationState.activeConversationId);
  const messageEndRef = useRef(null);

  const activeConversation = useMemo(
    () =>
      conversationState.conversations.find(
        (conversation) => conversation.id === conversationState.activeConversationId,
      ) ?? conversationState.conversations[0],
    [conversationState],
  );
  const messages = activeConversation?.messages ?? [];
  const activeSources = useMemo(
    () => messages.find((message) => message.id === sourceMessageId)?.sources ?? [],
    [messages, sourceMessageId],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => saveConversationState(conversationState), 180);
    return () => window.clearTimeout(timer);
  }, [conversationState]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const updateConversation = (conversationId, updater) => {
    setConversationState((current) => ({
      ...current,
      conversations: current.conversations.map((conversation) =>
        conversation.id === conversationId ? updater(conversation) : conversation,
      ),
    }));
  };

  const updateMessages = (conversationId, updater) => {
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      messages: updater(conversation.messages),
      updatedAt: new Date().toISOString(),
    }));
  };

  const selectSourceMessage = (message) => {
    const sources = Array.isArray(message?.sources) ? message.sources : [];
    setSourceMessageId(sources.length ? message.id : null);
    setSelectedSourceId(sources[0]?.document_id ?? null);
  };

  const submitQuestion = async (event) => {
    event.preventDefault();
    const value = question.trim();
    if (!value || sending || !activeConversation) return;

    const conversationId = activeConversation.id;
    const timestamp = Date.now();
    const assistantId = `assistant-${timestamp}`;
    const hasUserMessage = activeConversation.messages.some((message) => message.role === "user");
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      title:
        !conversation.isTitleCustom && !hasUserMessage
          ? titleFromQuestion(value)
          : conversation.title,
      messages: [
        ...conversation.messages,
        { id: `user-${timestamp}`, role: "user", content: value, sources: [] },
        {
          id: assistantId,
          role: "assistant",
          content: "",
          progress: "질문을 준비하고 있습니다…",
          pending: true,
          sources: [],
        },
      ],
      updatedAt: new Date().toISOString(),
    }));
    setQuestion("");
    setSending(true);
    setSourceMessageId(null);
    setSelectedSourceId(null);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const data = await streamQuestion(value, {
        signal: controller.signal,
        onEvent: (streamEvent) => {
          updateMessages(conversationId, (current) =>
            current.map((message) => {
              if (message.id !== assistantId) return message;
              if (streamEvent.token) {
                return { ...message, content: `${message.content}${streamEvent.token}` };
              }
              if (streamEvent.stage && streamEvent.stage !== "done") {
                return { ...message, progress: streamEvent.stage };
              }
              return message;
            }),
          );
        },
      });

      const sources = Array.isArray(data.sources) ? data.sources : [];
      updateMessages(conversationId, (current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                pending: false,
                progress: "",
                content: data.answer || message.content || "답변이 비어 있습니다.",
                sources,
                images: Array.isArray(data.images) ? data.images : [],
                contextCount: data.n_context_chunks,
                cacheHit: data.cache_hit,
                timings: Array.isArray(data.stage_timings) ? data.stage_timings : [],
              }
            : message,
        ),
      );
      if (activeConversationIdRef.current === conversationId) {
        setSourceMessageId(sources.length ? assistantId : null);
        setSelectedSourceId(sources[0]?.document_id ?? null);
      }
    } catch (error) {
      updateMessages(conversationId, (current) =>
        current.map((message) =>
          message.id === assistantId
            ? {
                ...message,
                role: error.name === "AbortError" ? "assistant" : "error",
                pending: false,
                progress: "",
                content:
                  error.name === "AbortError"
                    ? message.content || "답변 생성을 중지했습니다."
                    : error.message,
              }
            : message,
        ),
      );
    } finally {
      if (abortRef.current === controller) {
        setSending(false);
        abortRef.current = null;
      }
    }
  };

  const switchConversation = (conversationId) => {
    const target = conversationState.conversations.find(
      (conversation) => conversation.id === conversationId,
    );
    if (!target || conversationId === conversationState.activeConversationId) return;
    abortRef.current?.abort();
    abortRef.current = null;
    activeConversationIdRef.current = conversationId;
    setSending(false);
    setConversationState((current) => ({ ...current, activeConversationId: conversationId }));
    setQuestion("");
    const latestId = latestSourceMessageId(target.messages);
    const sourceMessage = target.messages.find((message) => message.id === latestId);
    selectSourceMessage(sourceMessage);
    setMobileSourcesOpen(false);
  };

  const startNewChat = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    const conversation = createConversation();
    activeConversationIdRef.current = conversation.id;
    setSending(false);
    setConversationState((current) => ({
      conversations: [conversation, ...current.conversations],
      activeConversationId: conversation.id,
    }));
    setQuestion("");
    setSourceMessageId(null);
    setSelectedSourceId(null);
    setMobileSourcesOpen(false);
  };

  const renameConversation = (conversationId, nextTitle) => {
    const title = String(nextTitle).trim().slice(0, MAX_CONVERSATION_TITLE_LENGTH);
    if (!title) return;
    updateConversation(conversationId, (conversation) => ({
      ...conversation,
      title,
      isTitleCustom: true,
      updatedAt: new Date().toISOString(),
    }));
  };

  const deleteConversation = (conversationId = conversationState.activeConversationId) => {
    const deletingActive = conversationId === conversationState.activeConversationId;
    if (deletingActive) {
      abortRef.current?.abort();
      abortRef.current = null;
    }

    const remaining = conversationState.conversations.filter(
      (conversation) => conversation.id !== conversationId,
    );
    const conversations = remaining.length ? remaining : [createConversation()];
    const activeConversationId = deletingActive
      ? conversations[0].id
      : conversationState.activeConversationId;
    activeConversationIdRef.current = activeConversationId;
    setConversationState({ conversations, activeConversationId });

    if (deletingActive) {
      setSending(false);
      setQuestion("");
      const nextConversation = conversations.find(
        (conversation) => conversation.id === activeConversationId,
      );
      const latestId = latestSourceMessageId(nextConversation?.messages ?? []);
      const sourceMessage = nextConversation?.messages.find(
        (message) => message.id === latestId,
      );
      selectSourceMessage(sourceMessage);
      setMobileSourcesOpen(false);
    }
  };

  const showSources = (message) => {
    selectSourceMessage(message);
    setMobileSourcesOpen(true);
  };

  return {
    conversations: conversationState.conversations,
    activeConversationId: conversationState.activeConversationId,
    activeConversation,
    messages,
    question,
    setQuestion,
    sending,
    activeSources,
    selectedSourceId,
    setSelectedSourceId,
    mobileSourcesOpen,
    setMobileSourcesOpen,
    messageEndRef,
    submitQuestion,
    stopAnswer: () => abortRef.current?.abort(),
    startNewChat,
    switchConversation,
    renameConversation,
    deleteConversation,
    canDeleteConversation: Boolean(activeConversation),
    showSources,
    defaultTitle: DEFAULT_CONVERSATION_TITLE,
  };
}
