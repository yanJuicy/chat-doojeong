import ConversationList from "../conversations/ConversationList";

export default function LeftRail({
  onNewChat,
  onDeleteChat,
  canDeleteChat,
  conversations,
  activeConversationId,
  onSelectConversation,
  onRenameConversation,
  onDeleteConversation,
  onOpenDocuments,
  documentCount,
  onOpenReports,
  mobileOpen = false,
  onCloseMobile,
}) {
  return (
    <aside className={`left-rail ${mobileOpen ? "mobile-open" : ""}`}>
      <button
        className="mobile-rail-close"
        type="button"
        onClick={onCloseMobile}
        aria-label="대화 목록 닫기"
      >
        닫기 ×
      </button>
      <div className="brand-mark" aria-label="Document intelligence">
        <span>DI</span>
        <div>
          <strong>Document</strong>
          <small>intelligence</small>
        </div>
      </div>

      <button className="new-chat" type="button" onClick={onNewChat}>
        <span>새 채팅</span>
        <b aria-hidden="true">＋</b>
      </button>

      <nav aria-label="주요 메뉴">
        <button className="nav-item active" type="button">
          <span aria-hidden="true">⌁</span>
          대화 내역
        </button>
        <button className="nav-item" type="button" onClick={onOpenDocuments}>
          <span aria-hidden="true">▤</span>
          문서 관리
          <b>{documentCount}</b>
        </button>
        <button className="nav-item" type="button" onClick={onOpenReports}>
          <span aria-hidden="true">📝</span>
          업무 보고서
        </button>
        <button
          className="nav-item delete-chat"
          type="button"
          onClick={onDeleteChat}
          disabled={!canDeleteChat}
        >
          <span aria-hidden="true">×</span>
          현재 대화 삭제
        </button>
      </nav>

      <ConversationList
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelect={onSelectConversation}
        onRename={onRenameConversation}
        onDelete={onDeleteConversation}
      />

      <div className="rail-note">
        <strong>데이터는 내부에서 처리됩니다</strong>
        <p>브라우저는 FastAPI를 통해서만 DB와 RAG에 접근합니다.</p>
      </div>
    </aside>
  );
}
