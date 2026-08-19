import { useRef, useState } from "react";
import { weeklyReportDocxUrl } from "../../api";

function formatPeriodLabel(period) {
  return `${period.start} ~ ${period.end}`;
}

function EntryRow({ entry, onEdit, onDelete }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(entry.content);

  const commit = () => {
    const trimmed = draft.trim();
    setEditing(false);
    if (trimmed && trimmed !== entry.content) onEdit(entry.id, trimmed);
    else setDraft(entry.content);
  };

  if (editing) {
    return (
      <li className="weekly-report-entry editing">
        <input
          type="text"
          value={draft}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") commit();
            if (event.key === "Escape") {
              setDraft(entry.content);
              setEditing(false);
            }
          }}
          onBlur={commit}
        />
      </li>
    );
  }

  return (
    <li className="weekly-report-entry">
      <span onClick={() => setEditing(true)}>{entry.content}</span>
      <button type="button" onClick={() => setEditing(true)} aria-label="항목 수정">
        수정
      </button>
      <button type="button" onClick={() => onDelete(entry.id)} aria-label="항목 삭제">
        삭제
      </button>
    </li>
  );
}

export default function WeeklyReportDrawer({
  open,
  onClose,
  department,
  onDepartmentChange,
  text,
  onTextChange,
  onSubmit,
  submitting,
  loadingEntries,
  currentPeriod,
  nextPeriod,
  currentWeekEntries,
  nextWeekEntries,
  onEditEntry,
  onDeleteEntry,
  onUploadDocument,
  uploading,
}) {
  const fileInputRef = useRef(null);

  if (!open) return null;

  return (
    <>
      <div
        className="drawer-backdrop"
        role="presentation"
        onMouseDown={(event) => event.target === event.currentTarget && onClose()}
      >
        <section
          className="document-drawer weekly-report-drawer"
          role="dialog"
          aria-modal="true"
          aria-labelledby="weekly-report-title"
        >
          <header className="drawer-header">
            <div>
              <p className="eyebrow">WEEKLY REPORT</p>
              <h2 id="weekly-report-title">주간보고서 모드</h2>
              <span>이번 주 한 일과 다음 주 계획을 자유롭게 입력하면 항목별로 정리해서 쌓아둡니다.</span>
            </div>
            <button type="button" onClick={onClose} aria-label="주간보고서 모드 닫기">
              닫기 ×
            </button>
          </header>

          <div className="weekly-report-body">
            <label className="weekly-report-field">
              <span>부서명</span>
              <input
                type="text"
                value={department}
                onChange={(event) => onDepartmentChange(event.target.value)}
                placeholder="예: 시군 특화 일자리 사업단"
              />
            </label>

            <form
              className="composer weekly-report-composer"
              onSubmit={(event) => {
                event.preventDefault();
                onSubmit();
              }}
            >
              <label htmlFor="weekly-report-text" className="sr-only">
                업무 내용 입력
              </label>
              <textarea
                id="weekly-report-text"
                value={text}
                onChange={(event) => onTextChange(event.target.value)}
                onKeyDown={(event) => {
                  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="예: 이번주는 강사 간담회하고 보조금 집행도 좀 했고, 다음주엔 기업 모집공고 낼거야"
                rows={4}
                disabled={submitting}
              />
              <div className="composer-footer">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    event.target.value = "";
                    if (file) onUploadDocument(file);
                  }}
                />
                <button
                  type="button"
                  className="weekly-report-upload-button"
                  disabled={uploading}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading ? "업로드 중..." : "기존 보고서 문서 업로드(PDF)"}
                </button>
                <span className="composer-shortcut">Ctrl/⌘ + Enter</span>
                <button type="submit" disabled={submitting || !text.trim() || !department.trim()}>
                  {submitting ? "정리하는 중..." : "저장하기"}
                </button>
              </div>
            </form>

            <div className="weekly-report-lists">
              <section className="weekly-report-list">
                <h3>
                  이번 주 실적 <span>{formatPeriodLabel(currentPeriod)}</span>
                </h3>
                {loadingEntries && <p className="weekly-report-empty">불러오는 중...</p>}
                {!loadingEntries && currentWeekEntries.length === 0 && (
                  <p className="weekly-report-empty">아직 입력된 실적이 없습니다.</p>
                )}
                <ul>
                  {currentWeekEntries.map((entry) => (
                    <EntryRow key={entry.id} entry={entry} onEdit={onEditEntry} onDelete={onDeleteEntry} />
                  ))}
                </ul>
              </section>

              <section className="weekly-report-list">
                <h3>
                  다음 주 계획 <span>{formatPeriodLabel(nextPeriod)}</span>
                </h3>
                {loadingEntries && <p className="weekly-report-empty">불러오는 중...</p>}
                {!loadingEntries && nextWeekEntries.length === 0 && (
                  <p className="weekly-report-empty">아직 입력된 계획이 없습니다.</p>
                )}
                <ul>
                  {nextWeekEntries.map((entry) => (
                    <EntryRow key={entry.id} entry={entry} onEdit={onEditEntry} onDelete={onDeleteEntry} />
                  ))}
                </ul>
              </section>
            </div>

            <div className="weekly-report-generate">
              <div>
                <b>주간보고서 생성</b>
                <span>지금까지 쌓인 항목으로 양식에 맞춘 DOCX를 바로 받습니다.</span>
              </div>
              <a
                className={`weekly-report-generate-button${
                  !department.trim() || (currentWeekEntries.length === 0 && nextWeekEntries.length === 0)
                    ? " disabled"
                    : ""
                }`}
                href={weeklyReportDocxUrl({ department, currentPeriod, nextPeriod })}
                onClick={(event) => {
                  if (!department.trim() || (currentWeekEntries.length === 0 && nextWeekEntries.length === 0)) {
                    event.preventDefault();
                  }
                }}
              >
                주간보고서 생성(DOCX)
              </a>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
