import { documentFileUrl } from "../../api";
import { formatPercent } from "../../utils/format";

export default function SourceCard({ source, index, selected, onSelect }) {
  const similarity = formatPercent(source.similarity);

  return (
    <a
      className={`source-card ${selected ? "active" : ""}`}
      href={documentFileUrl(source.document_id, source.page_number)}
      target="_blank"
      rel="noreferrer"
      onClick={() => onSelect(source.document_id)}
    >
      <div className="source-card-top">
        <span>{index + 1}</span>
        <strong>{source.filename}</strong>
      </div>
      <p>
        {source.page_number ? `${source.page_number}페이지` : "페이지 정보 없음"}
        {similarity && ` · 관련도 ${similarity}`}
      </p>
      <small>
        {source.page_number ? `${source.page_number}페이지에서 열기` : "원문 열기"} ↗
      </small>
    </a>
  );
}
