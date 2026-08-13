import { useState } from "react";
import { assetUrl, documentFileUrl } from "../../api";
import useDocumentDetail from "../../hooks/useDocumentDetail";
import { STATUS_LABELS } from "../../constants/documents";
import {
  canDeleteDocument,
  documentStatusClass,
  formatDateTime,
} from "../../utils/documents";
import DocumentProgress from "./DocumentProgress";
import LabelEditor from "./LabelEditor";

export default function DocumentDetailModal({
  documentId,
  onClose,
  onDelete,
  onSaveLabels,
  onRetry,
  onReextract,
  actionPending,
}) {
  const { detail, labels, chunks, loading, error, refresh } = useDocumentDetail(documentId);
  const [expandedChunks, setExpandedChunks] = useState(false);

  if (!documentId) return null;

  const saveLabels = async (nextLabels) => {
    if (await onSaveLabels(documentId, nextLabels)) await refresh();
  };

  const retry = async () => {
    if (await onRetry(documentId)) await refresh();
  };

  const reextract = async () => {
    if (!window.confirm("기존 OCR·청크·벡터를 지우고 원문 추출부터 다시 진행할까요?")) return;
    if (await onReextract(documentId)) await refresh();
  };

  const remove = async () => {
    if (!detail || !window.confirm(`'${detail.filename}' 문서를 완전히 삭제할까요?`)) return;
    const result = await onDelete([documentId]);
    if (result?.deleted?.includes(documentId)) onClose();
  };

  return (
    <div className="detail-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="document-detail" role="dialog" aria-modal="true" aria-labelledby="detail-title">
        <header className="detail-header">
          <div>
            <p className="eyebrow">DOCUMENT DETAIL</p>
            <h2 id="detail-title">{detail?.filename ?? "문서 상세"}</h2>
          </div>
          <button type="button" onClick={onClose}>닫기 ×</button>
        </header>

        <div className="detail-body">
          {loading && !detail && <div className="detail-loading">문서 정보를 불러오는 중입니다.</div>}
          {error && <div className="drawer-error">{error}</div>}
          {detail && (
            <>
              <section className="detail-overview">
                <div className="detail-status-line">
                  <span className={`document-status ${documentStatusClass(detail.status)}`}>
                    {STATUS_LABELS[detail.status] ?? detail.status}
                  </span>
                  <a href={documentFileUrl(documentId)} target="_blank" rel="noreferrer">
                    원문 열기 ↗
                  </a>
                </div>
                <DocumentProgress document={detail} />
                {detail.error_message && (
                  <div className="detail-message error"><b>실패 원인</b>{detail.error_message}</div>
                )}
                {detail.warning_message && (
                  <div className="detail-message warning"><b>확인 사항</b>{detail.warning_message}</div>
                )}
                <dl className="detail-meta">
                  <div><dt>추출 방식</dt><dd>{detail.extraction_method ?? "-"}</dd></div>
                  <div><dt>추출 품질</dt><dd>{Number.isFinite(detail.extraction_quality_score) ? `${Math.round(detail.extraction_quality_score * 100)}점` : "-"}</dd></div>
                  <div><dt>재시도 횟수</dt><dd>{detail.retry_count ?? 0}회</dd></div>
                  <div><dt>검색 등록</dt><dd>{formatDateTime(detail.indexed_at)}</dd></div>
                </dl>
                <div className="detail-actions">
                  {["failed", "needs_review", "extracting"].includes(detail.status) && (
                    <button type="button" onClick={retry} disabled={actionPending}>다시 처리</button>
                  )}
                  <button
                    type="button"
                    onClick={reextract}
                    disabled={actionPending || !canDeleteDocument(detail)}
                    title={!canDeleteDocument(detail) ? "현재 처리 단계가 끝난 뒤 다시 실행할 수 있습니다." : undefined}
                  >
                    OCR부터 다시 처리
                  </button>
                  <button
                    type="button"
                    className="danger"
                    onClick={remove}
                    disabled={actionPending || !canDeleteDocument(detail)}
                    title={!canDeleteDocument(detail) ? "처리 중인 문서는 완료 후 삭제할 수 있습니다." : undefined}
                  >
                    문서 삭제
                  </button>
                </div>
              </section>

              <LabelEditor labels={labels} onSave={saveLabels} disabled={actionPending} />

              <section className="detail-section">
                <div className="detail-section-heading">
                  <div>
                    <b>추출 청크</b>
                    <span>
                      전체 {chunks.summary?.total ?? 0} · 텍스트 {chunks.summary?.text ?? 0} · 표 {chunks.summary?.table ?? 0} · 이미지 {chunks.summary?.image ?? 0}
                    </span>
                  </div>
                  {chunks.items.length > 5 && (
                    <button type="button" onClick={() => setExpandedChunks((value) => !value)}>
                      {expandedChunks ? "접기" : "전체 보기"}
                    </button>
                  )}
                </div>
                <div className="chunk-list">
                  {chunks.items.length === 0 && <div className="document-empty">아직 생성된 청크가 없습니다.</div>}
                  {chunks.items.slice(0, expandedChunks ? chunks.items.length : 5).map((chunk, index) => (
                    <article className="chunk-card" key={chunk.chunk_id}>
                      <div>
                        <b>#{index + 1} · {chunk.chunk_type}</b>
                        {chunk.page_number && (
                          <a href={documentFileUrl(documentId, chunk.page_number)} target="_blank" rel="noreferrer">
                            {chunk.page_number}페이지 ↗
                          </a>
                        )}
                      </div>
                      <p>{chunk.text}</p>
                      {chunk.image_url && <img src={assetUrl(chunk.image_url)} alt="문서에서 추출한 이미지" />}
                    </article>
                  ))}
                </div>
              </section>
            </>
          )}
        </div>
      </section>
    </div>
  );
}
