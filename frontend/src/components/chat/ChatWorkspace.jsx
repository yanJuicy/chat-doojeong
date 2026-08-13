import ChatComposer from "./ChatComposer";
import ChatMessage from "./ChatMessage";
import TopBar from "../layout/TopBar";

export default function ChatWorkspace({
  health,
  onOpenDocuments,
  onOpenConversations,
  messages,
  onShowSources,
  messageEndRef,
  question,
  onQuestionChange,
  onSubmit,
  onStop,
  sending,
  readyDocumentCount,
}) {
  return (
    <main className="chat-workspace">
      <TopBar
        health={health}
        onOpenDocuments={onOpenDocuments}
        onOpenConversations={onOpenConversations}
      />
      <section className="message-list" aria-live="polite">
        {messages.map((message) => (
          <ChatMessage
            key={message.id}
            message={message}
            onShowSources={onShowSources}
          />
        ))}
        <div ref={messageEndRef} />
      </section>
      <ChatComposer
        question={question}
        onQuestionChange={onQuestionChange}
        onSubmit={onSubmit}
        onStop={onStop}
        sending={sending}
        readyDocumentCount={readyDocumentCount}
      />
    </main>
  );
}
