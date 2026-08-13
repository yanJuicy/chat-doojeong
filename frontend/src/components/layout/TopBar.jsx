import { getServerView } from "../../utils/server";

export default function TopBar({ health, onOpenDocuments, onOpenConversations }) {
  const server = getServerView(health);

  return (
    <header className="topbar">
      <div>
        <p className="eyebrow">INTERNAL KNOWLEDGE</p>
        <h1>두정테크 문서 AI</h1>
      </div>
      <div className="mobile-topbar-actions">
        <button type="button" onClick={onOpenConversations}>대화</button>
        <button type="button" onClick={onOpenDocuments}>문서 관리</button>
      </div>
      <span className={`server-badge ${server.key}`} title={server.title}>
        <span aria-hidden="true" /> {server.label}
      </span>
    </header>
  );
}
