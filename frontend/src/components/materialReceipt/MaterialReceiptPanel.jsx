// frontend/src/components/materialReceipt/MaterialReceiptPanel.jsx
// (가칭) — DailyReportDrawer.jsx 와 같은 위치/패턴을 따른다고 가정.
// 실제 프로젝트의 className/디자인 토큰에 맞춰 스타일만 조정하면 된다.

import { useState } from "react";

const API_BASE = ""; // 프로젝트의 기존 api.js 베이스 URL과 동일하게 맞출 것

export default function MaterialReceiptPanel() {
  const [orderFile, setOrderFile] = useState(null);
  const [xlsxFile, setXlsxFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  async function handlePreview() {
    if (!orderFile || !xlsxFile) {
      setError("주문서(.doc)와 자재입출고 엑셀(.xlsx) 파일을 모두 선택해주세요.");
      return;
    }
    setError(null);
    setLoading(true);
    setPreview(null);
    try {
      const form = new FormData();
      form.append("order_file", orderFile);
      form.append("xlsx_file", xlsxFile);
      const res = await fetch(`${API_BASE}/api/material-receipt/preview`, {
        method: "POST",
        body: form,
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "미리보기에 실패했습니다.");
      setPreview(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleApply() {
    if (!orderFile || !xlsxFile) return;
    setError(null);
    setLoading(true);
    try {
      const form = new FormData();
      form.append("order_file", orderFile);
      form.append("xlsx_file", xlsxFile);
      const res = await fetch(`${API_BASE}/api/material-receipt/apply`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || "적용에 실패했습니다.");
      }
      const blob = await res.blob();
      const unmatchedCount = res.headers.get("X-Unmatched-Count");
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = xlsxFile.name.replace(/\.xlsx$/, "") + "_수정됨.xlsx";
      a.click();
      URL.revokeObjectURL(url);
      if (unmatchedCount && Number(unmatchedCount) > 0) {
        setError(
          `저장은 완료됐지만, ${unmatchedCount}개 품목은 시트에서 못 찾아 반영되지 않았습니다. 미리보기 결과를 확인하세요.`
        );
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-4 space-y-4">
      <div>
        <h2 className="text-lg font-semibold">자재입출고 자동 반영</h2>
        <p className="text-sm text-gray-500">
          거래처 주문서(구매입고 내역 .doc)를 올리면, 자재입출고 엑셀의 해당 날짜·품목 수량 칸을 자동으로 채웁니다.
        </p>
      </div>

      <div className="space-y-2">
        <label className="block text-sm font-medium">거래처 주문서 (.doc)</label>
        <input
          type="file"
          accept=".doc,.html"
          onChange={(e) => setOrderFile(e.target.files?.[0] ?? null)}
        />
      </div>

      <div className="space-y-2">
        <label className="block text-sm font-medium">자재입출고 엑셀 (.xlsx)</label>
        <input
          type="file"
          accept=".xlsx"
          onChange={(e) => setXlsxFile(e.target.files?.[0] ?? null)}
        />
      </div>

      <div className="flex gap-2">
        <button
          onClick={handlePreview}
          disabled={loading}
          className="px-4 py-2 rounded border border-gray-300 disabled:opacity-50"
        >
          {loading ? "확인 중..." : "미리보기"}
        </button>
        <button
          onClick={handleApply}
          disabled={loading || !preview || preview.matched.length === 0}
          className="px-4 py-2 rounded bg-emerald-700 text-white disabled:opacity-50"
        >
          {loading ? "처리 중..." : "적용하고 다운로드"}
        </button>
      </div>

      {error && (
        <div className="text-sm text-red-600 border border-red-200 bg-red-50 rounded p-3">
          {error}
        </div>
      )}

      {preview && (
        <div className="space-y-3 border rounded p-3">
          <div className="text-sm text-gray-600">
            <div>거래처: <b>{preview.order.vendor}</b></div>
            <div>작성일: <b>{preview.order.written_at?.slice(0, 10)}</b></div>
            <div>대상 시트: <b>{preview.sheet_period}</b></div>
          </div>

          {preview.matched.length > 0 && (
            <div>
              <div className="text-sm font-medium text-emerald-700 mb-1">
                반영될 품목 ({preview.matched.length}건)
              </div>
              <ul className="text-sm space-y-1">
                {preview.matched.map((m) => (
                  <li key={m.cell}>
                    {m.item_code} ({m.item_name}) → {m.cell}에 +{m.quantity}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {preview.unmatched.length > 0 && (
            <div>
              <div className="text-sm font-medium text-amber-700 mb-1">
                시트에서 못 찾은 품목 ({preview.unmatched.length}건) — 수동 확인 필요
              </div>
              <ul className="text-sm space-y-1">
                {preview.unmatched.map((u) => (
                  <li key={u.item_code}>
                    {u.item_code} ({u.item_name}) — {u.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
