import { assetUrl } from "../../api";

export default function ChatMessage({ message, onShowSources }) {
  const isUser = message.role === "user";
  const isError = message.role === "error";
  const totalSeconds = message.timings?.reduce(
    (sum, timing) => sum + (Number(timing.seconds) || 0),
    0,
  );

  return (
    <article className={`message ${isUser ? "user" : "assistant"} ${isError ? "error" : ""}`}>
      <div className="message-avatar" aria-hidden="true">
        {isUser ? "나" : isError ? "!" : "AI"}
      </div>
      <div className="message-content">
        <div className="message-meta">
          <strong>{isUser ? "사용자" : isError ? "오류" : "문서 AI"}</strong>
          {message.cacheHit && <span>캐시 답변</span>}
        </div>
        {message.content && <p>{message.content}</p>}
        {message.pending && (
          <div className="loading-line">
            <i /><i /><i />
            <span>{message.progress || "답변을 만들고 있습니다…"}</span>
          </div>
        )}
        {message.images?.length > 0 && (
          <div className="answer-images">
            {message.images.map((image, index) => (
              <a
                href={assetUrl(image.image_url)}
                target="_blank"
                rel="noreferrer"
                key={`${image.chunk_id}-${index}`}
              >
                <img
                  src={assetUrl(image.image_url)}
                  alt={image.caption || `답변 참고 이미지 ${index + 1}`}
                />
                {image.caption && <span>{image.caption}</span>}
              </a>
            ))}
          </div>
        )}
        {!isUser && !isError && message.sources?.length > 0 && (
          <button
            type="button"
            className="source-link"
            onClick={() => onShowSources(message)}
          >
            출처 {message.sources.length}개 보기
            {Number.isFinite(message.contextCount) && ` · 근거 청크 ${message.contextCount}개`}
            {totalSeconds > 0 && ` · ${totalSeconds.toFixed(1)}초`}
          </button>
        )}
      </div>
    </article>
  );
}
