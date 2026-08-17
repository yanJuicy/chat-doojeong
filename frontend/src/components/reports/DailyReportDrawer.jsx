import useDailyReport from "../../hooks/useDailyReport";

function downloadMarkdown(result) {
  const blob = new Blob([result.body_markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${result.title}.md`;
  link.click();
  URL.revokeObjectURL(url);
}

export default function DailyReportDrawer({ open, onClose }) {
  const {
    form, updateField, generate, generating, result, issues, reset,
    query, setQuery, searchReference, referenceItems, searching, searchError,
    appendToReferenceNote,
  } = useDailyReport();

  if (!open) return null;

  return (
    <div
      className="drawer-backdrop"
      role="presentation"
      onMouseDown={(event) => event.target === event.currentTarget && onClose()}
    >
      <section className="document-drawer" role="dialog" aria-modal="true" aria-labelledby="report-title">
        <header className="drawer-header">
          <div>
            <p className="eyebrow">DAILY REPORT</p>
            <h2 id="report-title">업무 보고서</h2>
            <span>오늘 한 일을 입력하고, 필요하면 참고자료를 찾아 붙여넣으세요.</span>
          </div>
          <button type="button" onClick={onClose} aria-label="업무 보고서 닫기">
            닫기 ×
          </button>
        </header>

        <div className="drawer-body">
          <section className="upload-section">
            <div className="section-heading">
              <div>
                <b>참고자료 검색</b>
                <span>기존 문서와 이전 채팅 기록에서 찾아 보고서에 붙여넣을 수 있습니다.</span>
              </div>
            </div>
            <div className="library-filters">
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && searchReference()}
                placeholder="예: 로봇공학, 두정테크 용접방식"
                aria-label="참고자료 검색어"
              />
              <button type="button" onClick={searchReference} disabled={searching}>
                {searching ? "검색 중…" : "검색"}
              </button>
            </div>
            {searchError && <div className="drawer-error">{searchError}</div>}
            <div className="chunk-list">
              {referenceItems.length === 0 && !searching && (
                <div className="document-empty">검색어를 입력하고 검색해 보세요.</div>
              )}
              {referenceItems.map((item) => (
                <article className="chunk-card" key={`${item.source}-${item.reference_id}`}>
                  <div>
                    <b>{item.source === "document" ? "📄" : "💬"} {item.title}</b>
                    <button type="button" onClick={() => appendToReferenceNote(item)}>
                      보고서에 추가
                    </button>
                  </div>
                  <p>{item.snippet}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="library-section">
            <div className="section-heading">
              <div>
                <b>보고서 작성</b>
                <span>작성자와 오늘 한 일은 필수입니다.</span>
              </div>
            </div>

            {issues.length > 0 && (
              <div className="drawer-error">
                {issues.map((issue, index) => <div key={index}>{issue.message}</div>)}
              </div>
            )}

            <div className="upload-workspace">
              <label>
                날짜
                <input
                  type="date"
                  value={form.report_date}
                  onChange={(event) => updateField("report_date", event.target.value)}
                />
              </label>
              <label>
                작성자
                <input
                  type="text"
                  value={form.author}
                  onChange={(event) => updateField("author", event.target.value)}
                  placeholder="이름"
                />
              </label>
              <label>
                오늘 한 일
                <textarea
                  rows={4}
                  value={form.tasks_completed}
                  onChange={(event) => updateField("tasks_completed", event.target.value)}
                />
              </label>
              <label>
                특이사항 (선택)
                <textarea
                  rows={2}
                  value={form.issues}
                  onChange={(event) => updateField("issues", event.target.value)}
                />
              </label>
              <label>
                내일 계획 (선택)
                <textarea
                  rows={2}
                  value={form.tomorrow_plan}
                  onChange={(event) => updateField("tomorrow_plan", event.target.value)}
                />
              </label>
              <label>
                참고자료 (선택 — 위에서 "보고서에 추가" 누르면 여기 채워집니다)
                <textarea
                  rows={4}
                  value={form.reference_note}
                  onChange={(event) => updateField("reference_note", event.target.value)}
                />
              </label>

              <div className="upload-action">
                <button type="button" onClick={reset} disabled={generating}>초기화</button>
                <button type="button" onClick={generate} disabled={generating}>
                  {generating ? "생성 중…" : "보고서 생성"}
                </button>
              </div>
            </div>

            {result && (
              <article className="chunk-card">
                <div>
                  <b>{result.title}</b>
                  <button type="button" onClick={() => downloadMarkdown(result)}>
                    .md 파일로 다운로드
                  </button>
                </div>
                <pre style={{ whiteSpace: "pre-wrap" }}>{result.body_markdown}</pre>
              </article>
            )}
          </section>
        </div>
      </section>
    </div>
  );
}
