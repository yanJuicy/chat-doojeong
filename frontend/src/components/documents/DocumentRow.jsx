import { documentFileUrl } from "../../api";
import { STATUS_LABELS } from "../../constants/documents";
import { documentStatusClass } from "../../utils/documents";
import DocumentProgress from "./DocumentProgress";

export default function DocumentRow({
  document,
  selected,
  onToggle,
  onOpenDetail,
}) {
  return (
    <article className={`document-row ${selected ? "selected" : ""}`}>
      <label className="document-checkbox" aria-label={`${document.filename} 선택`}>
        <input
          type="checkbox"
          checked={selected}
          onChange={(event) => onToggle(document.document_id, event.target.checked)}
        />
      </label>
      <button type="button" className="document-main" onClick={() => onOpenDetail(document.document_id)}>
        <span className="document-icon" aria-hidden="true">DOC</span>
        <span className="document-info">
          <strong>{document.filename}</strong>
          <span>
            {document.labels?.length ? document.labels.join(" · ") : "라벨 없음"}
            {document.warning_message && " · 확인 필요"}
          </span>
          <DocumentProgress document={document} compact />
        </span>
      </button>
      <div className="document-row-side">
        <span className={`document-status ${documentStatusClass(document.status)}`}>
          {STATUS_LABELS[document.status] ?? document.status}
        </span>
        <a
          href={documentFileUrl(document.document_id)}
          target="_blank"
          rel="noreferrer"
          aria-label={`${document.filename} 원문 열기`}
        >
          원문 ↗
        </a>
      </div>
    </article>
  );
}
