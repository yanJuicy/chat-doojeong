import { useCallback, useEffect, useState } from "react";
import {
  getDocumentChunks,
  getDocumentLabels,
  getDocumentStatus,
} from "../api";
import { PROCESSING_STATUSES } from "../constants/documents";

export default function useDocumentDetail(documentId) {
  const [detail, setDetail] = useState(null);
  const [labels, setLabels] = useState([]);
  const [chunks, setChunks] = useState({ summary: {}, items: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async ({ quiet = false } = {}) => {
    if (!documentId) return;
    if (!quiet) setLoading(true);
    setError("");
    try {
      const [statusResult, labelsResult, chunksResult] = await Promise.all([
        getDocumentStatus(documentId),
        getDocumentLabels(documentId),
        getDocumentChunks(documentId),
      ]);
      setDetail(statusResult);
      setLabels(Array.isArray(labelsResult) ? labelsResult : []);
      setChunks(chunksResult?.items ? chunksResult : { summary: {}, items: [] });
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [documentId]);

  useEffect(() => {
    if (!documentId) {
      setDetail(null);
      setLabels([]);
      setChunks({ summary: {}, items: [] });
      return undefined;
    }
    load();
    return undefined;
  }, [documentId, load]);

  useEffect(() => {
    if (!documentId || !detail || !PROCESSING_STATUSES.has(detail.status)) return undefined;
    const timer = window.setInterval(() => load({ quiet: true }), 3000);
    return () => window.clearInterval(timer);
  }, [detail, documentId, load]);

  return { detail, labels, chunks, loading, error, refresh: load };
}
