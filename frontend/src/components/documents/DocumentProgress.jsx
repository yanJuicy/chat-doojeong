import { documentProgress } from "../../utils/documents";

export default function DocumentProgress({ document, compact = false }) {
  const progress = documentProgress(document);

  return (
    <div className={`document-progress ${compact ? "compact" : ""}`}>
      <span>{progress.label}</span>
      {Number.isFinite(progress.percent) && (
        <div className="progress-track" aria-label={`처리 진행률 ${progress.percent}%`}>
          <i style={{ width: `${progress.percent}%` }} />
        </div>
      )}
    </div>
  );
}
