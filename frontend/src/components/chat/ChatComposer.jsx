export default function ChatComposer({
  question,
  onQuestionChange,
  onSubmit,
  onStop,
  sending,
  readyDocumentCount,
}) {
  return (
    <form className="composer" onSubmit={onSubmit}>
      <label htmlFor="question" className="sr-only">질문 입력</label>
      <textarea
        id="question"
        value={question}
        onChange={(event) => onQuestionChange(event.target.value)}
        onKeyDown={(event) => {
          if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        placeholder="등록된 문서에 관해 질문하세요"
        rows={3}
        disabled={sending}
      />
      <div className="composer-footer">
        <span>전체 검색 가능 문서 {readyDocumentCount}개</span>
        <span className="composer-shortcut">Ctrl/⌘ + Enter</span>
        <button
          type={sending ? "button" : "submit"}
          disabled={!sending && !question.trim()}
          onClick={sending ? onStop : undefined}
        >
          {sending ? "생성 중지" : "질문 보내기"}
        </button>
      </div>
    </form>
  );
}
