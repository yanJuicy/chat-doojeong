import { useEffect, useMemo, useState } from "react";
import { PROCESSING_STATUSES } from "../../constants/documents";
import CommonLabelInput from "./CommonLabelInput";
import DocumentDetailModal from "./DocumentDetailModal";
import DocumentRow from "./DocumentRow";
import DocumentSummary from "./DocumentSummary";
import UploadItem from "./UploadItem";

export default function DocumentLibraryPanel({
  documents,
  loading,
  error,
  onRefresh,
  onRunWorkers,
  workersStarting,
  uploadItems,
  onAddFiles,
  onRemoveFile,
  onUpdateLabels,
  onApplyCommonLabels,
  onUpload,
  uploading,
  fileInputRef,
  onDeleteDocuments,
  onSaveLabels,
  onRetry,
  onReextract,
  actionPending,
}) {
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [dragging, setDragging] = useState(false);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [detailDocumentId, setDetailDocumentId] = useState(null);

  const filteredDocuments = useMemo(() => {
    const query = search.trim().toLowerCase();
    return documents.filter((document) => {
      const matchesSearch =
        !query ||
        document.filename?.toLowerCase().includes(query) ||
        document.labels?.some((label) => label.toLowerCase().includes(query));
      const matchesStatus =
        status === "all" ||
        (status === "ready" && document.status === "ready") ||
        (status === "processing" && PROCESSING_STATUSES.has(document.status)) ||
        (status === "attention" && ["failed", "needs_review"].includes(document.status));
      return matchesSearch && matchesStatus;
    });
  }, [documents, search, status]);

  useEffect(() => {
    const availableIds = new Set(documents.map((document) => document.document_id));
    setSelectedIds((current) => new Set([...current].filter((id) => availableIds.has(id))));
    if (detailDocumentId && !availableIds.has(detailDocumentId)) setDetailDocumentId(null);
  }, [detailDocumentId, documents]);

  const filteredIds = filteredDocuments.map((document) => document.document_id);
  const allFilteredSelected = filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id));

  const toggleDocument = (documentId, checked) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(documentId);
      else next.delete(documentId);
      return next;
    });
  };

  const toggleAllFiltered = () => {
    setSelectedIds((current) => {
      const next = new Set(current);
      filteredIds.forEach((id) => {
        if (allFilteredSelected) next.delete(id);
        else next.add(id);
      });
      return next;
    });
  };

  const deleteSelected = async () => {
    const ids = [...selectedIds];
    if (!ids.length || !window.confirm(`선택한 문서 ${ids.length}개를 완전히 삭제할까요?`)) return;
    const result = await onDeleteDocuments(ids);
    if (result?.deleted?.length) {
      setSelectedIds((current) => {
        const next = new Set(current);
        result.deleted.forEach((id) => next.delete(id));
        return next;
      });
    }
  };

  return (
    <div className="drawer-body">
      <section className="upload-section">
        <div className="section-heading">
          <div>
            <b>새 문서 등록</b>
            <span>파일마다 검색 라벨을 지정할 수 있습니다.</span>
          </div>
          <span>{uploadItems.length}개 선택</span>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          multiple
          accept=".pdf,.docx,.txt,.md,.html,.htm,.jpg,.jpeg,.png,.zip"
          onChange={(event) => {
            onAddFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <button
          type="button"
          className={`upload-drop ${dragging ? "dragging" : ""}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            onAddFiles(event.dataTransfer.files);
          }}
        >
          <b>파일을 끌어놓거나 눌러서 선택</b>
          <span>PDF, DOCX, TXT, MD, HTML, JPG, PNG, ZIP</span>
        </button>

        {uploadItems.length > 0 && (
          <div className="upload-workspace">
            <CommonLabelInput onApply={onApplyCommonLabels} />
            <div className="upload-items">
              {uploadItems.map((item) => (
                <UploadItem
                  key={item.id}
                  item={item}
                  onRemove={() => onRemoveFile(item.id)}
                  onChangeLabels={(labels) => onUpdateLabels(item.id, labels)}
                />
              ))}
            </div>
            <div className="upload-action">
              <span>라벨을 확인한 뒤 서버에 등록하세요.</span>
              <button type="button" onClick={onUpload} disabled={uploading}>
                {uploading ? "업로드 중…" : `${uploadItems.length}개 업로드`}
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="library-section">
        <div className="section-heading">
          <div>
            <b>등록된 문서</b>
            <span>처리 중 문서는 5초마다 자동 갱신됩니다.</span>
          </div>
          <div className="library-actions">
            {documents.some((document) => document.status === "uploaded") && (
              <button
                type="button"
                className="run-workers-button"
                onClick={onRunWorkers}
                disabled={workersStarting}
              >
                {workersStarting ? "시작 중…" : "처리 시작"}
              </button>
            )}
            <button type="button" className="refresh-button" onClick={onRefresh} disabled={loading}>
              {loading ? "불러오는 중" : "새로고침"}
            </button>
          </div>
        </div>
        <DocumentSummary documents={documents} />
        <div className="library-filters">
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="파일명 또는 라벨 검색"
            aria-label="문서 검색"
          />
          <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="문서 상태 필터">
            <option value="all">모든 상태</option>
            <option value="ready">검색 가능</option>
            <option value="processing">처리 중</option>
            <option value="attention">확인 필요</option>
          </select>
        </div>

        <div className="selection-toolbar">
          <label>
            <input
              type="checkbox"
              checked={allFilteredSelected}
              onChange={toggleAllFiltered}
              disabled={!filteredIds.length}
            />
            현재 목록 전체 선택
          </label>
          <span>{selectedIds.size}개 선택</span>
          <button
            type="button"
            className="danger-button"
            onClick={deleteSelected}
            disabled={!selectedIds.size || actionPending}
          >
            선택 삭제
          </button>
        </div>

        {error && <div className="drawer-error">{error}</div>}

        <div className="document-list">
          {!loading && !filteredDocuments.length && (
            <div className="document-empty">조건에 맞는 문서가 없습니다.</div>
          )}
          {filteredDocuments.map((document) => (
            <DocumentRow
              key={document.document_id}
              document={document}
              selected={selectedIds.has(document.document_id)}
              onToggle={toggleDocument}
              onOpenDetail={setDetailDocumentId}
            />
          ))}
        </div>
      </section>
      <DocumentDetailModal
        documentId={detailDocumentId}
        onClose={() => setDetailDocumentId(null)}
        onDelete={onDeleteDocuments}
        onSaveLabels={onSaveLabels}
        onRetry={onRetry}
        onReextract={onReextract}
        actionPending={actionPending}
      />
    </div>
  );
}
