import SourceCard from "./SourceCard";

export default function SourceList({ sources, selectedId, onSelect }) {
  return (
    <div className="source-list">
      {sources.map((source, index) => (
        <SourceCard
          key={`${source.document_id}-${source.page_number ?? index}`}
          source={source}
          index={index}
          selected={selectedId === source.document_id}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
