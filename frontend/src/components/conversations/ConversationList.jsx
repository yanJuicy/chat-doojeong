import { useState } from "react";
import { MAX_CONVERSATION_TITLE_LENGTH } from "../../constants/chat";

function formatUpdatedAt(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("ko-KR", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export default function ConversationList({
  conversations,
  activeConversationId,
  onSelect,
  onRename,
  onDelete,
}) {
  const [editingId, setEditingId] = useState(null);
  const [title, setTitle] = useState("");

  const beginEditing = (conversation) => {
    setEditingId(conversation.id);
    setTitle(conversation.title);
  };

  const finishEditing = (event) => {
    event.preventDefault();
    if (!title.trim()) return;
    onRename(editingId, title);
    setEditingId(null);
  };

  return (
    <section className="conversation-history" aria-label="이전 대화 목록">
      <div className="conversation-history-heading">
        <strong>이전 대화</strong>
        <span>{conversations.length}</span>
      </div>

      <div className="conversation-list">
        {conversations.map((conversation) => (
          <article
            className={`conversation-item ${
              conversation.id === activeConversationId ? "active" : ""
            }`}
            key={conversation.id}
          >
            {editingId === conversation.id ? (
              <form className="conversation-title-form" onSubmit={finishEditing}>
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  maxLength={MAX_CONVERSATION_TITLE_LENGTH}
                  aria-label="대화 제목"
                  autoFocus
                />
                <button type="submit" disabled={!title.trim()}>저장</button>
                <button type="button" onClick={() => setEditingId(null)}>취소</button>
              </form>
            ) : (
              <>
                <button
                  className="conversation-select"
                  type="button"
                  onClick={() => onSelect(conversation.id)}
                  aria-current={conversation.id === activeConversationId ? "true" : undefined}
                >
                  <strong>{conversation.title}</strong>
                  <small>{formatUpdatedAt(conversation.updatedAt)}</small>
                </button>
                <div className="conversation-actions">
                  <button
                    type="button"
                    onClick={() => beginEditing(conversation)}
                    aria-label={`${conversation.title} 제목 수정`}
                  >
                    수정
                  </button>
                  <button
                    className="delete"
                    type="button"
                    onClick={() => onDelete(conversation.id)}
                    aria-label={`${conversation.title} 대화 삭제`}
                  >
                    삭제
                  </button>
                </div>
              </>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}
