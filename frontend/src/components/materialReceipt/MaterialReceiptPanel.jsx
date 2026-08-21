// frontend/src/components/materialReceipt/MaterialReceiptPanel.jsx
//
// DocumentDrawer.jsx와 완전히 동일한 CSS 클래스(drawer-backdrop, document-drawer,
// upload-drop, document-row 등)를 그대로 재사용한다 — 이 프로젝트는 Tailwind가 아니라
// styles.css의 커스텀 클래스 체계를 쓰고 있어서, 새 클래스를 만드는 대신 기존 것을 빌려 쓴다.
//
// 문서관리와 다른 점: "새 문서 등록"은 파일 하나하나가 독립적이지만, 여기서는
//   1) 자재입출고 엑셀(기준 파일)을 하나 먼저 올리고
//   2) 거래처 주문서(.doc)는 여러 개를 큐에 쌓았다가
//   3) "전체 적용"을 누르면 큐를 순서대로 하나씩 반영한다 — 매 반영 결과가
//      다음 반영의 "기준 파일"이 되어 이어진다("연속 적용").

import { useRef, useState } from "react";

const API_BASE = "";

function formatBytes(bytes) {
  if (!bytes && bytes !== 0) return "";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

export default function MaterialReceiptPanel({ open, onClose }) {
  const xlsxInputRef = useRef(null);
  const orderInputRef = useRef(null);

  const [xlsxDragging, setXlsxDragging] = useState(false);
  const [orderDragging, setOrderDragging] = useState(false);

  const [workingFile, setWorkingFile] = useState(null);
  const [originalName, setOriginalName] = useState("");

  const [queue, setQueue] = useState([]);
  const [results, setResults] = useState([]);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState(null);

  if (!open) return null;

  function pickXlsxFiles(fileList) {
    const file = fileList?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setError("자재입출고 파일은 .xlsx만 올릴 수 있습니다.");
      return;
    }
    setError(null);
    setWorkingFile(file);
    setOriginalName(file.name);
    setResults([]);
  }

  function pickOrderFiles(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    const items = files.map((file) => ({
      id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      status: "pending",
    }));
    setQueue((current) => [...current, ...items]);
  }

  function removeQueueItem(id) {
    setQueue((current) => current.filter((item) => item.id !== id));
  }

  async function applyAll() {
    if (!workingFile) {
      setError("먼저 자재입출고 엑셀 파일을 올려주세요.");
      return;
    }
    const pendingItems = queue.filter((item) => item.status === "pending" || item.status === "error");
    if (!pendingItems.length) return;

    setProcessing(true);
    setError(null);
    let currentFile = workingFile;

    for (const item of pendingItems) {
      setQueue((current) => current.map((q) => (q.id === item.id ? { ...q, status: "applying" } : q)));

      try {
        const previewForm = new FormData();
        previewForm.append("order_file", item.file);
        previewForm.append("xlsx_file", currentFile);
        const previewRes = await fetch(`${API_BASE}/api/material-receipt/preview`, {
          method: "POST",
          body: previewForm,
        });
        const previewData = await previewRes.json();
        if (!previewRes.ok) throw new Error(previewData.detail || "미리보기 실패");

        const applyForm = new FormData();
        applyForm.append("order_file", item.file);
        applyForm.append("xlsx_file", currentFile);
        const applyRes = await fetch(`${API_BASE}/api/material-receipt/apply`, {
          method: "POST",
          body: applyForm,
        });
        if (!applyRes.ok) {
          const errData = await applyRes.json().catch(() => ({}));
          throw new Error(errData.detail || "반영 실패");
        }
        const blob = await applyRes.blob();
        currentFile = new File([blob], originalName || workingFile.name, {
          type: blob.type,
        });

        setResults((current) => [
          {
            id: item.id,
            filename: item.file.name,
            vendor: previewData.order?.vendor,
            writtenAt: previewData.order?.written_at,
            sheetPeriod: previewData.sheet_period,
            matched: previewData.matched || [],
            unmatched: previewData.unmatched || [],
          },
          ...current,
        ]);
        setQueue((current) => current.map((q) => (q.id === item.id ? { ...q, status: "done" } : q)));
      } catch (e) {
        setQueue((current) =>
          current.map((q) => (q.id === item.id ? { ...q, status: "error", errorMsg: e.message } : q)),
        );
      }
    }

    setWorkingFile(currentFile);
    setProcessing(false);
  }

  function downloadCurrent() {
    if (!workingFile) return;
    const url = URL.createObjectURL(workingFile);
    const a = document.createElement("a");
    a.href = url;
    a.download = (originalName || workingFile.name).replace(/\.xlsx$/, "") + "_반영됨.xlsx";
    a.click();
    URL.revokeObjectURL(url);
  }

  function resetAll() {
    setWorkingFile(null);
    setOriginalName("");
    setQueue([]);
    setResults([]);
    setError(null);
  }

  const pendingCount = queue.filter((item) => item.status === "pending" || item.status === "error").length;
  const doneCount = queue.filter((item) => item.status === "done").length;

  return (
    <>
      <div
        className="drawer-backdrop"
        role="presentation"
        onMouseDown={(event) => event.target === event.currentTarget && onClose()}
      >
        <section
          className="document-drawer"
          role="dialog"
          aria-modal="true"
          aria-labelledby="material-receipt-title"
        >
          <header className="drawer-header">
            <div>
              <p className="eyebrow">MATERIAL RECEIPT</p>
              <h2 id="material-receipt-title">자재입출고 자동 반영</h2>
              <span>거래처 주문서를 올리면 자재입출고 엑셀의 해당 날짜·품목 수량 칸을 자동으로 채웁니다.</span>
            </div>
            <button type="button" onClick={onClose} aria-label="자재입출고 닫기">
              닫기 ×
            </button>
          </header>

          <div className="drawer-body">
            <section className="upload-section">
              <div className="section-heading">
                <div>
                  <b>자재입출고 엑셀</b>
                  <span>먼저 기준이 될 엑셀 파일을 올려주세요.</span>
                </div>
                {workingFile && <span>선택됨</span>}
              </div>
              <input
                ref={xlsxInputRef}
                type="file"
                hidden
                accept=".xlsx"
                onChange={(event) => {
                  pickXlsxFiles(event.target.files);
                  event.target.value = "";
                }}
              />
              <button
                type="button"
                className={`upload-drop ${xlsxDragging ? "dragging" : ""}`}
                onClick={() => xlsxInputRef.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault();
                  setXlsxDragging(true);
                }}
                onDragLeave={() => setXlsxDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setXlsxDragging(false);
                  pickXlsxFiles(event.dataTransfer.files);
                }}
              >
                <b>{workingFile ? workingFile.name : "엑셀 파일을 끌어놓거나 눌러서 선택"}</b>
                <span>
                  {workingFile
                    ? `${formatBytes(workingFile.size)} · 다른 파일을 올리면 교체됩니다`
                    : "XLSX (자재입출고 양식)"}
                </span>
              </button>

              <div className="section-heading">
                <div>
                  <b>거래처 주문서</b>
                  <span>여러 건을 올리면 순서대로 이어서 반영됩니다.</span>
                </div>
                <span>{queue.length}개 대기열</span>
              </div>
              <input
                ref={orderInputRef}
                type="file"
                hidden
                multiple
                accept=".doc,.html,.htm"
                onChange={(event) => {
                  pickOrderFiles(event.target.files);
                  event.target.value = "";
                }}
              />
              <button
                type="button"
                className={`upload-drop ${orderDragging ? "dragging" : ""}`}
                onClick={() => orderInputRef.current?.click()}
                onDragOver={(event) => {
                  event.preventDefault();
                  setOrderDragging(true);
                }}
                onDragLeave={() => setOrderDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setOrderDragging(false);
                  pickOrderFiles(event.dataTransfer.files);
                }}
              >
                <b>주문서를 끌어놓거나 눌러서 선택</b>
                <span>DOC (구매입고 내역, 여러 개 가능)</span>
              </button>

              {queue.length > 0 && (
                <div className="upload-workspace">
                  <div className="upload-items">
                    {queue.map((item) => (
                      <div key={item.id} className="document-row">
                        <span className="document-icon" aria-hidden="true">DOC</span>
                        <span className="document-info">
                          <strong>{item.file.name}</strong>
                          <span>
                            {formatBytes(item.file.size)}
                            {item.status === "error" && item.errorMsg ? ` · ${item.errorMsg}` : ""}
                          </span>
                        </span>
                        <div className="document-row-side">
                          <span className="document-status">
                            {{
                              pending: "대기",
                              applying: "반영 중…",
                              done: "완료",
                              error: "실패",
                            }[item.status]}
                          </span>
                          {item.status !== "applying" && (
                            <button type="button" onClick={() => removeQueueItem(item.id)} aria-label="제거">
                              ×
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="upload-action">
                    <span>
                      {pendingCount > 0 ? `${pendingCount}건 반영 대기 중` : `${doneCount}건 모두 반영 완료`}
                    </span>
                    <button type="button" onClick={applyAll} disabled={processing || !pendingCount || !workingFile}>
                      {processing ? "반영 중…" : `${pendingCount}건 전체 적용`}
                    </button>
                  </div>
                </div>
              )}
            </section>

            <section className="library-section">
              <div className="section-heading">
                <div>
                  <b>반영 내역</b>
                  <span>적용한 순서대로 표시됩니다.</span>
                </div>
                <div className="library-actions">
                  <button type="button" className="refresh-button" onClick={resetAll}>
                    초기화
                  </button>
                </div>
              </div>

              {error && <div className="drawer-error">{error}</div>}

              <div className="document-list">
                {!results.length && (
                  <div className="document-empty">
                    엑셀과 주문서를 올리고 "전체 적용"을 누르면 여기에 결과가 쌓입니다.
                  </div>
                )}
                {results.map((r) => (
                  <article key={r.id} className="document-row">
                    <span className="document-icon" aria-hidden="true">DOC</span>
                    <span className="document-info">
                      <strong>{r.filename}</strong>
                      <span>
                        {r.vendor} · {r.writtenAt?.slice(0, 10)} · {r.sheetPeriod}
                      </span>
                      <span style={{ display: "block", marginTop: 4 }}>
                        매칭 {r.matched.length}건
                        {r.unmatched.length > 0 && ` · 미매칭 ${r.unmatched.length}건`}
                        {r.matched.length > 0 &&
                          ": " +
                            r.matched
                              .slice(0, 3)
                              .map((m) => `${m.item_code}→${m.cell}+${m.quantity}`)
                              .join(", ") +
                            (r.matched.length > 3 ? " 외" : "")}
                      </span>
                      {r.unmatched.length > 0 && (
                        <span style={{ display: "block", marginTop: 2, color: "#a13f3f" }}>
                          미매칭: {r.unmatched.map((u) => u.item_code).join(", ")}
                        </span>
                      )}
                    </span>
                  </article>
                ))}
              </div>

              {results.length > 0 && (
                <div className="upload-action">
                  <span>지금까지 {results.length}건 반영된 최종 파일을 받을 수 있습니다.</span>
                  <button type="button" onClick={downloadCurrent}>
                    최종 파일 다운로드
                  </button>
                </div>
              )}
            </section>
          </div>
        </section>
      </div>
    </>
  );
}
