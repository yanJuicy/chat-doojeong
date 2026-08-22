import { useState } from "react";
import MaterialReceiptPanel from "../materialReceipt/MaterialReceiptPanel";
import WeeklyReportPanel from "../weekly-report/WeeklyReportPanel";
import DocumentLibraryPanel from "./DocumentLibraryPanel";

const TABS = [
  { id: "documents", label: "문서 목록" },
  { id: "weeklyReport", label: "주간보고서" },
  { id: "materialReceipt", label: "자재입출고" },
];

export default function DocumentDrawer({ open, onClose, weeklyReport, ...libraryProps }) {
  const [activeTab, setActiveTab] = useState("documents");

  if (!open) return null;

  return (
    <div
      className="drawer-backdrop"
      role="presentation"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section
        className="document-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="document-title"
      >
        <header className="drawer-header">
          <div>
            <p className="eyebrow">KNOWLEDGE BASE</p>
            <h2 id="document-title">문서 관리</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="문서 관리 닫기">
            닫기 ×
          </button>
        </header>

        <div className="drawer-tabs" role="tablist" aria-label="문서 관리 탭">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              className={`drawer-tab ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="drawer-tab-panel">
          {activeTab === "documents" && <DocumentLibraryPanel {...libraryProps} />}
          {activeTab === "weeklyReport" && <WeeklyReportPanel weeklyReport={weeklyReport} />}
          {activeTab === "materialReceipt" && <MaterialReceiptPanel />}
        </div>
      </section>
    </div>
  );
}
