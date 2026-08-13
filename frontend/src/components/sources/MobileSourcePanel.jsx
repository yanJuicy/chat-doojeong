import SourceList from "./SourceList";

export default function MobileSourcePanel({
  open,
  sources,
  selectedId,
  onSelect,
  onClose,
}) {
  if (!open) return null;

  return (
    <div
      className="mobile-source-backdrop"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section
        className="mobile-source-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mobile-source-title"
      >
        <header>
          <div>
            <p className="eyebrow">EVIDENCE</p>
            <h2 id="mobile-source-title">선택한 답변의 출처</h2>
          </div>
          <button type="button" onClick={onClose}>닫기 ×</button>
        </header>
        <SourceList sources={sources} selectedId={selectedId} onSelect={onSelect} />
      </section>
    </div>
  );
}
