export default function DocumentSummary({ documents }) {
  const counts = documents.reduce(
    (result, document) => {
      result.total += 1;
      if (document.status === "ready") result.ready += 1;
      else if (["failed", "needs_review"].includes(document.status)) result.attention += 1;
      else result.processing += 1;
      return result;
    },
    { total: 0, ready: 0, processing: 0, attention: 0 },
  );

  return (
    <div className="document-summary" aria-label="문서 처리 현황">
      <span><b>{counts.total}</b> 전체</span>
      <span className="ready"><b>{counts.ready}</b> 검색 가능</span>
      <span className="processing"><b>{counts.processing}</b> 처리 중</span>
      <span className="attention"><b>{counts.attention}</b> 확인 필요</span>
    </div>
  );
}
