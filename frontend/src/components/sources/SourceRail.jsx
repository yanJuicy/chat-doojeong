import SourceList from "./SourceList";

export default function SourceRail({ sources, selectedId, onSelect }) {
  return (
    <aside className="source-rail" aria-label="답변 출처">
      <div className="source-header">
        <div>
          <p className="eyebrow">EVIDENCE</p>
          <h2>선택한 답변의 출처</h2>
        </div>
        <span>{sources.length}개</span>
      </div>

      {!sources.length ? (
        <div className="source-empty">
          <b>아직 표시할 출처가 없습니다</b>
          <p>AI 답변에 실제 사용된 출처만 여기에 표시됩니다.</p>
        </div>
      ) : (
        <SourceList sources={sources} selectedId={selectedId} onSelect={onSelect} />
      )}
    </aside>
  );
}
