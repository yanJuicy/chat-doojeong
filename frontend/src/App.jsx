import { useState } from "react";
import ChatWorkspace from "./components/chat/ChatWorkspace";
import DocumentDrawer from "./components/documents/DocumentDrawer";
import LeftRail from "./components/layout/LeftRail";
import MobileSourcePanel from "./components/sources/MobileSourcePanel";
import SourceRail from "./components/sources/SourceRail";
import WeeklyReportDrawer from "./components/weekly-report/WeeklyReportDrawer";
import useChat from "./hooks/useChat";
import useDocuments from "./hooks/useDocuments";
import useServerHealth from "./hooks/useServerHealth";
import useToast from "./hooks/useToast";
import useWeeklyReport from "./hooks/useWeeklyReport";

export default function App() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [weeklyReportOpen, setWeeklyReportOpen] = useState(false);
  const [conversationMenuOpen, setConversationMenuOpen] = useState(false);
  const { toast, showToast } = useToast();
  const health = useServerHealth();
  const chat = useChat();
  const documents = useDocuments(showToast);
  const weeklyReport = useWeeklyReport(showToast, () =>
    documents.loadDocuments({ quiet: true }),
  );
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
        documentCount={documents.documents.length}
        onOpenWeeklyReport={() => {
          setConversationMenuOpen(false);
          setWeeklyReportOpen(true);
        }}
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

      <WeeklyReportDrawer
        open={weeklyReportOpen}
        onClose={() => setWeeklyReportOpen(false)}
        department={weeklyReport.department}
        departments={weeklyReport.departments}
        onDepartmentChange={weeklyReport.setDepartment}
        text={weeklyReport.text}
        onTextChange={weeklyReport.setText}
        onSubmit={weeklyReport.submit}
        submitting={weeklyReport.submitting}
        loadingEntries={weeklyReport.loadingEntries}
        currentPeriod={weeklyReport.currentPeriod}
        nextPeriod={weeklyReport.nextPeriod}
        currentWeekEntries={weeklyReport.currentWeekEntries}
        nextWeekEntries={weeklyReport.nextWeekEntries}
        onEditEntry={weeklyReport.editEntry}
        onDeleteEntry={weeklyReport.removeEntry}
        onUploadDocument={weeklyReport.uploadDocument}
        uploading={weeklyReport.uploading}
      />

      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
