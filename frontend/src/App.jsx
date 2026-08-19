import { useState } from "react";
import ChatWorkspace from "./components/chat/ChatWorkspace";
import DocumentDrawer from "./components/documents/DocumentDrawer";
import LeftRail from "./components/layout/LeftRail";
import MaterialReceiptPanel from "./components/materialReceipt/MaterialReceiptPanel";
import MobileSourcePanel from "./components/sources/MobileSourcePanel";
import SourceRail from "./components/sources/SourceRail";
import useChat from "./hooks/useChat";
import useDocuments from "./hooks/useDocuments";
import useServerHealth from "./hooks/useServerHealth";
import useToast from "./hooks/useToast";

export default function App() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [materialReceiptOpen, setMaterialReceiptOpen] = useState(false);
  const [conversationMenuOpen, setConversationMenuOpen] = useState(false);
  const { toast, showToast } = useToast();
  const health = useServerHealth();
  const chat = useChat();
  const documents = useDocuments(showToast);
  const readyDocumentCount = documents.documents.filter(
    (document) => document.status === "ready",
  ).length;

  return (
    <div className="app-shell">
      <LeftRail
        onNewChat={() => {
          chat.startNewChat();
          setConversationMenuOpen(false);
        }}
        onDeleteChat={() => {
          if (window.confirm("현재 화면의 대화 내용을 삭제할까요?")) chat.deleteConversation();
        }}
        canDeleteChat={chat.canDeleteConversation}
        conversations={chat.conversations}
        activeConversationId={chat.activeConversationId}
        onSelectConversation={(conversationId) => {
          chat.switchConversation(conversationId);
          setConversationMenuOpen(false);
        }}
        onRenameConversation={chat.renameConversation}
        onDeleteConversation={(conversationId) => {
          const conversation = chat.conversations.find((item) => item.id === conversationId);
          if (window.confirm(`“${conversation?.title ?? "이 대화"}”를 삭제할까요?`)) {
            chat.deleteConversation(conversationId);
          }
        }}
        onOpenDocuments={() => {
          setConversationMenuOpen(false);
          setDrawerOpen(true);
        }}
        onOpenMaterialReceipt={() => {
          setConversationMenuOpen(false);
          setMaterialReceiptOpen(true);
        }}
        documentCount={documents.documents.length}
        mobileOpen={conversationMenuOpen}
        onCloseMobile={() => setConversationMenuOpen(false)}
      />

      {conversationMenuOpen && (
        <button
          className="mobile-rail-backdrop"
          type="button"
          onClick={() => setConversationMenuOpen(false)}
          aria-label="대화 목록 닫기"
        />
      )}

      <ChatWorkspace
        health={health}
        onOpenDocuments={() => setDrawerOpen(true)}
        onOpenConversations={() => setConversationMenuOpen(true)}
        messages={chat.messages}
        onShowSources={chat.showSources}
        messageEndRef={chat.messageEndRef}
        question={chat.question}
        onQuestionChange={chat.setQuestion}
        onSubmit={chat.submitQuestion}
        onStop={chat.stopAnswer}
        sending={chat.sending}
        readyDocumentCount={readyDocumentCount}
      />

      <SourceRail
        sources={chat.activeSources}
        selectedId={chat.selectedSourceId}
        onSelect={chat.setSelectedSourceId}
      />

      <MobileSourcePanel
        open={chat.mobileSourcesOpen}
        sources={chat.activeSources}
        selectedId={chat.selectedSourceId}
        onSelect={chat.setSelectedSourceId}
        onClose={() => chat.setMobileSourcesOpen(false)}
      />


      <DocumentDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        documents={documents.documents}
        loading={documents.loading}
        error={documents.error}
        onRefresh={() => documents.loadDocuments()}
        onRunWorkers={documents.startWorkers}
        workersStarting={documents.workersStarting}
        uploadItems={documents.uploadItems}
        onAddFiles={documents.addFiles}
        onRemoveFile={documents.removeFile}
        onUpdateLabels={documents.updateItemLabels}
        onApplyCommonLabels={documents.applyCommonLabels}
        onUpload={documents.uploadFiles}
        uploading={documents.uploading}
        fileInputRef={documents.fileInputRef}
        onDeleteDocuments={documents.removeDocuments}
        onSaveLabels={documents.saveLabels}
        onRetry={documents.retryProcessing}
        onReextract={documents.restartExtraction}
        actionPending={documents.actionPending}
      />
      {materialReceiptOpen && (
  <div
    style={{
      position: "fixed",
      inset: 0,
      zIndex: 9999,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      backgroundColor: "rgba(0,0,0,0.4)",
    }}
    onClick={() => setMaterialReceiptOpen(false)}
  >
    <div
      style={{
        backgroundColor: "white",
        borderRadius: "8px",
        boxShadow: "0 10px 30px rgba(0,0,0,0.3)",
        maxWidth: "560px",
        width: "90%",
        maxHeight: "90vh",
        overflowY: "auto",
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <div style={{ display: "flex", justifyContent: "flex-end", padding: "8px" }}>
        <button
          onClick={() => setMaterialReceiptOpen(false)}
          style={{
            background: "none",
            border: "none",
            fontSize: "20px",
            cursor: "pointer",
            padding: "4px 8px",
            color: "#666",
          }}
        >
          ×
        </button>
      </div>
      <MaterialReceiptPanel />
    </div>
  </div>
)}

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
